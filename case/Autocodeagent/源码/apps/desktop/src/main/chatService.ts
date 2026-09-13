/**
 * 对话服务（P1 起为 Orchestrator 入口）：
 * 保存用户消息 → 组装 ToolBus / PermissionGate / Checkpoint → runTurn 主循环。
 * Ask 权限经 stream:event 挂起，permission:resolve 通道回灌决策。
 */
import { randomUUID } from 'node:crypto';
import {
  buildSessionBus,
  Checkpoint,
  buildDiffView,
  compileWhitelist,
  createSkillTool,
  createTaskTool,
  createWebSearchTool,
  LlmClient,
  PermissionGate,
  ReadState,
  registerSecret,
  runTurn,
  toChangeSetView,
  type ConfigStore,
  type ExpertStore,
  type McpPool,
  type PermissionAnswer,
  type PermissionQuery,
  type SessionStore,
  type Tool,
  type UsageStore,
  type Workspace,
} from '@agent-core/agent-core';
import type { AppSettings, ChangeSetView, ChatImage, ChatMessage, DiffView, ModelConfig, NormalizedUsage, Risk, RollbackResult, SessionRunState, StreamEvent } from '@agentbuddy/shared';
import type { SkillHub } from '@agent-core/agent-core';

export type Emit = (event: StreamEvent) => void;

/** P6：Main 注入的密钥解密与用量落盘能力 */
export interface ChatServiceOptions {
  /** 从 KeyStore 取明文 Key（safeStorage 解密；空 = 未设置） */
  getKey?: (modelId: string) => Promise<string>;
  /** 用量 / 执行记录采集（usage.jsonl / records.jsonl） */
  usage?: UsageStore;
}

const zeroUsage = (): NormalizedUsage => ({ promptTokens: 0, completionTokens: 0, totalTokens: 0, cacheReadTokens: 0 });

export class ChatService {
  private readonly checkpoint: Checkpoint;
  private running = new Map<string, AbortController>();
  /** 挂起的权限询问：存全 query 字段（callId/name/risk/detail），使切换会话后能重建权限卡（permission_request 事件不重发） */
  private pendingPerms = new Map<string, { sessionId: string; callId: string; name: string; risk: Risk; detail: string; resolve: (a: PermissionAnswer) => void }>();
  /** P3：gate 按会话保留 → 「始终允许」跨轮复用；模式/白名单每轮热更新 */
  private gates = new Map<string, PermissionGate>();
  private askHandlers = new Map<string, (q: PermissionQuery) => Promise<PermissionAnswer>>();
  /** 权限请求串行队列（per-session）：并行子代理复用同一 gate，并发权限请求须排队弹卡（前端 pendingPermission 单值，同时多个会互相覆盖挂死） */
  private permQueue = new Map<string, Promise<unknown>>();
  /** Phase 2 按需加载：per-session 发现集（sessionId → 已发现的 MCP 工具名），跨多次 ask 累积；clear/delete 时重置 */
  private discovered = new Map<string, Set<string>>();

  constructor(
    private readonly sessions: SessionStore,
    private readonly configs: ConfigStore,
    private readonly workspace: Workspace,
    dataDir: string,
    private readonly skills?: SkillHub,
    /** P5：MCP 连接池（每轮并入工具总线 + ⑤层目录注入） */
    private readonly mcp?: McpPool,
    /** P7：专家存储（会话绑定 expertId 时套用人设与工具/技能限定） */
    private readonly experts?: ExpertStore,
    /** P6：密钥解密 + 用量落盘 */
    private readonly opts: ChatServiceOptions = {},
  ) {
    this.checkpoint = new Checkpoint(dataDir);
  }

  isBusy(sessionId: string): boolean {
    return this.running.has(sessionId);
  }

  abort(sessionId: string): boolean {
    const controller = this.running.get(sessionId);
    if (!controller) return false;
    controller.abort();
    // 挂起中的权限询问随中断解除（视为拒绝）
    for (const [reqId, pending] of [...this.pendingPerms]) {
      if (pending.sessionId === sessionId) {
        this.pendingPerms.delete(reqId);
        pending.resolve({ allow: false, remember: false });
      }
    }
    return true;
  }

  /**
   * 会话进行态快照（切换会话时前端据此对齐）：busy = 是否仍在跑 runTurn；pending = 挂起的权限询问。
   * permission_request 是一次性事件，切走会话即被前端 sessionId 过滤丢弃且不重发，故须由此主动查回重画权限卡。
   */
  runState(sessionId: string): SessionRunState {
    let pending: SessionRunState['pending'] = null;
    for (const [requestId, p] of this.pendingPerms) {
      if (p.sessionId === sessionId) {
        pending = { requestId, callId: p.callId, name: p.name, risk: p.risk, detail: p.detail };
        break;
      }
    }
    return { busy: this.running.has(sessionId), pending };
  }

  resolvePermission(requestId: string, allow: boolean, remember: boolean): boolean {
    const pending = this.pendingPerms.get(requestId);
    if (!pending) return false;
    this.pendingPerms.delete(requestId);
    pending.resolve({ allow, remember });
    return true;
  }

  async ask(sessionId: string, text: string, emit: Emit, skillName?: string, images?: ChatImage[]): Promise<void> {
    const exists = await this.sessions.get(sessionId);
    if (!exists) throw new Error('会话不存在');
    if (this.running.has(sessionId)) throw new Error('该会话正在生成中，请先停止');

    const userMessage: ChatMessage = { id: randomUUID(), role: 'user', content: text, createdAt: Date.now(), ...(images?.length ? { images } : {}) };
    await this.sessions.appendMessage(sessionId, userMessage);

    const stored = await this.configs.get();
    // P6：Key 仅在 Main 解密（safeStorage）；config.json 不再存明文
    const apiKey = (this.opts.getKey ? await this.opts.getKey(stored.id) : '') || stored.apiKey;
    registerSecret(apiKey);
    const config: ModelConfig = { ...stored, apiKey };
    if (!config.apiKey || !config.baseUrl) {
      emit({ type: 'error', sessionId, message: '请先在「模型配置」中填写 API Key 与 Base URL' });
      return;
    }
    // P3：每轮读取设置 → 盾牌切换立即生效；白名单空 = 内置默认
    const settings = await this.configs.getSettings();

    const controller = new AbortController();
    this.running.set(sessionId, controller);
    this.askHandlers.set(sessionId, (q) => this.askUserSerial(sessionId, q, emit, controller.signal));
    const gate = this.gateFor(sessionId);
    gate.update(settings.permissionMode, { execWhitelist: compileWhitelist(settings.execWhitelist) });
    // append 后再读：SessionStore 同一对象引用，messages 已含 userMessage，不可再拼一次（会重复）
    const latest = await this.sessions.get(sessionId);
    if (!latest) throw new Error('会话不存在');
    const messages = [...latest.messages];
    const total = zeroUsage();

    // P4：④层目录注入 + /name 触发正文（仅本轮高优先级指令）
    let skillCatalog = this.skills ? await this.skills.catalog() : undefined;
    let skillInstruction: string | undefined;
    if (skillName && this.skills) {
      const found = await this.skills.get(skillName);
      if (!found) throw new Error(`技能不存在或已禁用: ${skillName}`);
      if (!found.meta.enabled) throw new Error(`技能已禁用: ${skillName}（可在技能页启用）`);
      skillInstruction = found.body;
    }

    // P7：会话绑定专家 → 人设注入 + 技能目录限定 + 工具绑定过滤（配置数据驱动，Loop 无专家分支 §13）
    const expert = latest.expertId && this.experts ? await this.experts.get(latest.expertId) : null;
    if (expert) {
      if (skillCatalog && expert.skills.length > 0) skillCatalog = skillCatalog.filter((s) => expert.skills.includes(s.name));
      // /name 触发也受绑定限定（Renderer 菜单同源过滤，此处 Main 侧硬边界）
      if (skillName && expert.skills.length > 0 && !expert.skills.includes(skillName)) {
        throw new Error(`技能 /${skillName} 未绑定给专家「${expert.name}」`);
      }
    }

    // 内置 + 技能自取 + 已连接 MCP 工具合并；MCP 按 schema 合计 token 分流：小规模全量常驻，
    // 大规模转按需（deferred + search_tools 检索发现）；alwaysLoad 连接器强制常驻、跳过按需。详见 tools/bus.ts。
    // 技能自取工具：模型按④层目录自主 use_skill（普通/专家模式同源）；专家绑定清单作硬边界收口
    const skillTool = this.skills
      ? createSkillTool(this.skills, expert && expert.skills.length > 0 ? expert.skills : undefined)
      : null;
    // 联网搜索：设置开启且已配置 Tavily key → 注入 websearch（webfetch 已在内置总线，零配置）
    const webSearchTool = await this.buildWebSearchTool(settings);
    // task（子代理派发）：spawn 闭包捕获本会话 config/gate/emit/total，子代理复用之（详见 spawnSubagent）
    const taskTool = createTaskTool((eid, p, sig) => this.spawnSubagent(sessionId, eid, p, sig, { config, gate, emit, total }));
    const mcpTools = this.mcp?.sessionTools() ?? [];
    const extra = [skillTool, webSearchTool, taskTool].filter((t): t is Tool => t !== null);
    // alwaysLoadServers：强制常驻连接器名（pool 侧算，仅已连接且 cfg.alwaysLoad）
    const bus = buildSessionBus(mcpTools, expert?.tools, extra, { alwaysLoadServers: this.mcp?.alwaysLoadServers() });
    // ⑤层目录同步限定：只列绑定的连接器（未绑定时全量）
    let mcpCatalog = this.mcp?.catalog();
    if (mcpCatalog && expert && expert.tools.length > 0) {
      mcpCatalog = mcpCatalog.filter((c) => expert.tools.includes(`mcp:${c.name}`));
    }

    try {
      await runTurn({
        sessionId,
        messages,
        client: new LlmClient(config),
        config,
        bus,
        gate,
        checkpoint: this.checkpoint,
        readState: new ReadState(),
        workspace: this.workspace.activePath(),
        workspaceRoots: this.workspace.rootsList(),
        signal: controller.signal,
        emit,
        persist: (msg) => this.sessions.appendMessage(sessionId, msg).then(() => undefined),
        skillCatalog,
        skillInstruction,
        mcpCatalog,
        persona: expert?.persona || undefined,
        // Phase 2：per-session 发现集（跨多次 ask 累积 search_tools 命中，clear/delete 时重置）
        discovered: this.discoveredFor(sessionId),
        // 当前执行计划：注入 LLM 上下文，使模型在多次中断 / 历史裁剪后仍知道 todo 进度（不必靠翻旧 todo_write 调用去猜）
        todos: latest.todos ?? [],
        onTodos: (todos) => {
          void this.sessions.updateTodos(sessionId, todos); // 随会话落盘（防抖）；plan 事件由 Loop 发（§18）
        },
        onUsage: (u) => {
          total.promptTokens += u.promptTokens;
          total.completionTokens += u.completionTokens;
          total.totalTokens += u.totalTokens;
          total.cacheReadTokens += u.cacheReadTokens;
          // P6：每次响应归一用量追加 usage.jsonl（含缓存命中）
          void this.opts.usage?.recordUsage({
            sessionId,
            model: config.model,
            provider: config.provider,
            promptTokens: u.promptTokens,
            completionTokens: u.completionTokens,
            totalTokens: u.totalTokens,
            cacheReadTokens: u.cacheReadTokens,
          });
        },
        // P6：工具调用终态 → records.jsonl（执行记录回放）
        onRecord: (r) => {
          void this.opts.usage?.recordTool({ sessionId, ...r });
        },
      });
      await this.sessions.flush(sessionId);
      if (!controller.signal.aborted) {
        const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');
        emit({ type: 'done', sessionId, messageId: lastAssistant?.id ?? userMessage.id, usage: total });
        // P1 2.3：首轮正常结束 → 异步 LLM 自动命名（fire-and-forget，失败静默回退首条消息截断标题）
        if (latest.messages.length === 1) void this.autoTitle(sessionId, text, config, emit);
      }
    } catch (e) {
      await this.sessions.flush(sessionId).catch(() => undefined);
      if (controller.signal.aborted) {
        emit({ type: 'interrupted', sessionId });
      } else {
        emit({ type: 'error', sessionId, message: e instanceof Error ? e.message : String(e) });
      }
    } finally {
      this.running.delete(sessionId);
      this.askHandlers.delete(sessionId);
      this.permQueue.delete(sessionId);
    }
  }

  /** P1 2.3：首轮结束后异步生成会话标题（8~16 字概括；失败静默，回退首条消息截断标题） */
  private async autoTitle(sessionId: string, firstText: string, config: ModelConfig, emit: Emit): Promise<void> {
    try {
      const res = await new LlmClient(config).chat({
        messages: [
          { role: 'system', content: '你是会话标题生成器。根据用户首条消息生成一个 8~16 字的简短标题，概括任务主题。只输出标题文本：不要引号、标点结尾、编号或任何解释。' },
          { role: 'user', content: firstText.slice(0, 2000) },
        ],
        tools: [],
        temperature: 0.2,
        maxTokens: 60,
        signal: AbortSignal.timeout(20_000),
        onDelta: () => {}, // 非流式消费：标题一次性取归一结果
      });
      const title = res.message.content.replace(/[\r\n]+/g, ' ').replace(/^["'“”《]+|["'“”》]+$/g, '').trim().slice(0, 40);
      if (!title) return;
      const renamed = await this.sessions.rename(sessionId, title);
      if (renamed) emit({ type: 'title', sessionId, title: renamed.title });
    } catch {
      /* 自动命名是锦上添花：任何失败（超时 / 限流 / 解析）都静默忽略 */
    }
  }

  /**
   * 联网搜索工具注入：settings.websearch.enabled 且 KeyStore 存有 Tavily key 时构造，否则 null。
   * key 由 Main 解密（safeStorage）并在工厂内登记脱敏；未注入 getKey（如单测）则不启用。
   */
  private async buildWebSearchTool(settings: AppSettings): Promise<Tool | null> {
    if (!settings.websearch.enabled || !this.opts.getKey) return null;
    const apiKey = await this.opts.getKey('websearch');
    if (!apiKey) return null;
    return createWebSearchTool({ apiKey, provider: settings.websearch.provider });
  }

  /** 会话级 gate 工厂：ask 间接当轮 handler，abort 时 handler 随 finally 清理 */
  private gateFor(sessionId: string): PermissionGate {
    let gate = this.gates.get(sessionId);
    if (!gate) {
      gate = new PermissionGate('Ask', (q) => {
        const handler = this.askHandlers.get(sessionId);
        if (!handler) return Promise.resolve({ allow: false, remember: false });
        return handler(q);
      });
      this.gates.set(sessionId, gate);
    }
    return gate;
  }

  /** Phase 2：取（或惰性建）会话的按需发现集，注入 runTurn 使 search_tools 命中跨多次提问累积、不必重复检索 */
  private discoveredFor(sessionId: string): Set<string> {
    let set = this.discovered.get(sessionId);
    if (!set) {
      set = new Set<string>();
      this.discovered.set(sessionId, set);
    }
    return set;
  }

  /** Phase 2：清空 / 删除会话时重置其发现集（ipc 层调用）——下次提问重新按需检索，避免记住已随清空失效的工具名 */
  resetDiscovered(sessionId: string): void {
    this.discovered.delete(sessionId);
  }

  /** Ask 挂起：发 permission_request 事件，等 Renderer 回灌或 abort 解除 */
  private askUser(sessionId: string, query: PermissionQuery, emit: Emit, signal: AbortSignal): Promise<PermissionAnswer> {
    const requestId = randomUUID();
    return new Promise((resolve) => {
      const onAbort = (): void => {
        this.pendingPerms.delete(requestId);
        resolve({ allow: false, remember: false });
      };
      if (signal.aborted) return onAbort();
      signal.addEventListener('abort', onAbort, { once: true });
      this.pendingPerms.set(requestId, {
        sessionId,
        callId: query.callId,
        name: query.name,
        risk: query.risk,
        detail: query.detail,
        resolve: (answer) => {
          signal.removeEventListener('abort', onAbort);
          resolve(answer);
        },
      });
      emit({
        type: 'permission_request',
        sessionId,
        requestId,
        callId: query.callId,
        name: query.name,
        risk: query.risk,
        detail: query.detail,
      });
    });
  }

  /**
   * 权限请求串行化：并行子代理复用同一 per-session gate，若并发触发 askUser 会同时发多个 permission_request，
   * 前端单值 pendingPermission 只显示最后一个、其余挂死。用 promise 链把同会话的权限请求排成一队，一次弹一个卡。
   */
  private askUserSerial(sessionId: string, query: PermissionQuery, emit: Emit, signal: AbortSignal): Promise<PermissionAnswer> {
    const prev = this.permQueue.get(sessionId) ?? Promise.resolve();
    const cur = prev.then(() => this.askUser(sessionId, query, emit, signal));
    this.permQueue.set(sessionId, cur.then(() => undefined, () => undefined)); // 队列尾只用于串行，吞掉结果 / 异常
    return cur;
  }

  /**
   * 派发子代理（task 工具的 spawn 实现）：加载 expert → 独立上下文跑嵌套 runTurn → 返回其最终结果文本回灌主 agent。
   * 复用主会话 config/gate/checkpoint/workspace；子消息不落盘（persist no-op → 上下文隔离）；signal 透传（主停子停）；
   * usage 汇总进主 total（子 token 不漏计）；子 bus 不含 task（depth=1，防递归派发）；子内部事件静默，仅 error 提为 notice。
   */
  private async spawnSubagent(
    sessionId: string,
    expertId: string | undefined,
    prompt: string,
    signal: AbortSignal,
    parent: { config: ModelConfig; gate: PermissionGate; emit: Emit; total: NormalizedUsage },
  ): Promise<string> {
    const expert = expertId && this.experts ? await this.experts.get(expertId) : null;
    if (expertId && !expert) return `子代理派发失败：专家不存在（${expertId}）`;

    // 子工具集：内置 + 技能自取 + 联网，按 expert.tools/skills 限定；不含 task（depth=1，子代理不能再派）
    const settings = await this.configs.getSettings();
    const skillTool = this.skills
      ? createSkillTool(this.skills, expert && expert.skills.length > 0 ? expert.skills : undefined)
      : null;
    const webSearchTool = await this.buildWebSearchTool(settings);
    const mcpTools = this.mcp?.sessionTools() ?? [];
    const childExtra = [skillTool, webSearchTool].filter((t): t is Tool => t !== null);
    const bus = buildSessionBus(mcpTools, expert?.tools, childExtra, { alwaysLoadServers: this.mcp?.alwaysLoadServers() });

    let skillCatalog = this.skills ? await this.skills.catalog() : undefined;
    if (skillCatalog && expert && expert.skills.length > 0) skillCatalog = skillCatalog.filter((s) => expert.skills.includes(s.name));
    let mcpCatalog = this.mcp?.catalog();
    if (mcpCatalog && expert && expert.tools.length > 0) mcpCatalog = mcpCatalog.filter((c) => expert.tools.includes(`mcp:${c.name}`));

    const messages: ChatMessage[] = [{ id: randomUUID(), role: 'user', content: prompt, createdAt: Date.now() }];
    // 静默转发：子代理内部过程不混入主对话流，仅 error 提为 notice 让用户知晓子任务失败
    const childEmit: Emit = (e) => {
      if (e.type === 'error') parent.emit({ type: 'notice', sessionId, message: `子代理任务出错：${e.message}` });
    };

    await runTurn({
      sessionId,
      messages,
      client: new LlmClient(parent.config),
      config: parent.config,
      bus,
      gate: parent.gate,
      checkpoint: this.checkpoint,
      readState: new ReadState(),
      workspace: this.workspace.activePath(),
      workspaceRoots: this.workspace.rootsList(),
      signal,
      emit: childEmit,
      persist: async () => undefined, // 子消息不落盘：独立上下文，仅结果回灌主 agent
      skillCatalog,
      mcpCatalog,
      persona: expert?.persona || undefined,
      discovered: new Set<string>(), // 子独立发现集（不与主会话累积混用）
      onUsage: (u) => {
        parent.total.promptTokens += u.promptTokens;
        parent.total.completionTokens += u.completionTokens;
        parent.total.totalTokens += u.totalTokens;
        parent.total.cacheReadTokens += u.cacheReadTokens;
        void this.opts.usage?.recordUsage({
          sessionId,
          model: parent.config.model,
          provider: parent.config.provider,
          promptTokens: u.promptTokens,
          completionTokens: u.completionTokens,
          totalTokens: u.totalTokens,
          cacheReadTokens: u.cacheReadTokens,
        });
      },
      onRecord: (r) => {
        void this.opts.usage?.recordTool({ sessionId, ...r });
      },
    });

    if (signal.aborted) return '（子代理任务已随主任务中断）';
    const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');
    return (lastAssistant?.content || '').trim() || '（子代理未产出结果）';
  }

  /** 保存模型配置（供 ipc 层复用同一 configs 实例） */
  saveConfig(config: ModelConfig): Promise<ModelConfig> {
    return this.configs.upsert(config);
  }

  /* ── P2 审阅（右栏 Diff 面板，任务 2/4） ── */

  /** 会话审阅清单（倒序） */
  async listChanges(sessionId: string): Promise<ChangeSetView[]> {
    const sets = await this.checkpoint.list(sessionId);
    return sets.map(toChangeSetView);
  }

  /** 完整 Diff 视图（备份 = 旧侧，当前工作区 = 新侧） */
  async getDiff(changeId: string): Promise<DiffView> {
    const set = await this.checkpoint.get(changeId);
    if (!set) throw new Error(`快照不存在: ${changeId}`);
    return buildDiffView(this.checkpoint, set);
  }

  /** 接受：变更已在工作区，仅固化状态 */
  async acceptChange(changeId: string): Promise<ChangeSetView> {
    return toChangeSetView(await this.checkpoint.accept(changeId));
  }

  /** 撤销：按条目逐类还原 / git 整树 checkout */
  async revertChange(changeId: string): Promise<ChangeSetView> {
    return toChangeSetView(await this.checkpoint.restore(changeId));
  }

  /** 一键接受全部（Qoder 同款）：仅处理 pending，已审阅的跳过 */
  async acceptAll(sessionId: string): Promise<number> {
    const sets = await this.checkpoint.list(sessionId);
    let n = 0;
    for (const set of sets) {
      if (set.status !== 'pending') continue;
      await this.checkpoint.accept(set.changeId);
      n++;
    }
    return n;
  }

  /**
   * P2 3.3 节点回溯：回到某消息节点重来——
   * ① 收集该节点之后所有消息的 toolChangeId；
   * ② 逆序（newest→oldest）强制回滚，尊重备份链（B.backup = A 应用后的状态，正序会污染）；
   * ③ 从该节点分叉出新会话，原时间线保留。工作区全局共享，回滚全局生效。
   */
  async rollbackToNode(sessionId: string, messageId: string): Promise<RollbackResult> {
    const session = await this.sessions.get(sessionId);
    if (!session) throw new Error('会话不存在');
    const nodeIdx = session.messages.findIndex((m) => m.id === messageId);
    if (nodeIdx < 0) throw new Error('节点不存在');
    const changeIds: string[] = [];
    for (let i = nodeIdx + 1; i < session.messages.length; i++) {
      const cid = session.messages[i]?.toolChangeId;
      if (cid) changeIds.push(cid);
    }
    let restored = 0;
    for (const cid of [...changeIds].reverse()) {
      if (await this.checkpoint.restoreForRollback(cid)) restored++;
    }
    const branch = await this.sessions.branchFrom(sessionId, messageId);
    if (!branch) throw new Error('创建分支会话失败');
    return { branchSessionId: branch.id, restored };
  }
}
