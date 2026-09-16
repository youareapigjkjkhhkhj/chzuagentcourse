/**
 * 子代理派发器（task 工具的后端实现）：加载 expert → 独立上下文跑嵌套 runTurn → 返回结果文本回灌主 agent。
 * 从 ChatService 拆出（AGENTS §4/§5：使 ChatService 回归「会话编排」单一职责，本类专注「子代理派发」）。
 * 设计：复用主会话 config/gate/checkpoint/workspace；子消息不落盘（persist no-op → 上下文隔离）；
 * signal 透传（主停子停）；usage 汇总进主 total（子 token 不漏计）；子 bus 不含 task（depth=1 防递归派发）；
 * 子内部事件静默，仅 error 提为 notice。
 */
import { randomUUID } from 'node:crypto';
import {
  buildSessionBus,
  createSkillTool,
  LlmClient,
  ReadState,
  runTurn,
  type Checkpoint,
  type ConfigStore,
  type ExpertStore,
  type McpPool,
  type PermissionGate,
  type SkillHub,
  type Tool,
  type UsageStore,
  type Workspace,
} from '@agent-core/agent-core';
import type { AppSettings, ChatMessage, ModelConfig, NormalizedUsage } from '@agentbuddy/shared';
import type { Emit } from './chatService';

/** SubagentRunner 构造依赖：均来自 ChatService 已持有的 store / 能力（构造期一次注入） */
export interface SubagentDeps {
  configs: ConfigStore;
  checkpoint: Checkpoint;
  workspace: Workspace;
  experts?: ExpertStore;
  skills?: SkillHub;
  mcp?: McpPool;
  usage?: UsageStore;
  /** 联网搜索工具构造：与主 agent 同源（复用 ChatService.buildWebSearchTool，避免逻辑重复） */
  buildWebSearchTool: (settings: AppSettings) => Promise<Tool | null>;
}

/** 主会话注入的会话级上下文：每次 spawn 传入（子代理复用主模型 / 权限 / 事件出口 / 用量累加器） */
export interface SubagentParent {
  config: ModelConfig;
  gate: PermissionGate;
  emit: Emit;
  total: NormalizedUsage;
  /** 本次 task 调用 id（前端卡片 id）：子代理进度据此冒泡到主 agent 对应 task 卡片 */
  callId: string;
}

export class SubagentRunner {
  constructor(private readonly d: SubagentDeps) {}

  /** 派发一个子代理，返回其最终结果文本（作为主 agent task 工具的输出回灌） */
  async spawn(
    sessionId: string,
    expertId: string | undefined,
    prompt: string,
    signal: AbortSignal,
    parent: SubagentParent,
  ): Promise<string> {
    const expert = expertId && this.d.experts ? await this.d.experts.get(expertId) : null;
    if (expertId && !expert) return `子代理派发失败：专家不存在（${expertId}）`;

    // 子工具集：内置 + 技能自取 + 联网，按 expert.tools/skills 限定；不含 task（depth=1，子代理不能再派）
    const settings = await this.d.configs.getSettings();
    const skillTool = this.d.skills
      ? createSkillTool(this.d.skills, expert && expert.skills.length > 0 ? expert.skills : undefined)
      : null;
    const webSearchTool = await this.d.buildWebSearchTool(settings);
    const mcpTools = this.d.mcp?.sessionTools() ?? [];
    const childExtra = [skillTool, webSearchTool].filter((t): t is Tool => t !== null);
    const bus = buildSessionBus(mcpTools, expert?.tools, childExtra, { alwaysLoadServers: this.d.mcp?.alwaysLoadServers() });

    let skillCatalog = this.d.skills ? await this.d.skills.catalog() : undefined;
    if (skillCatalog && expert && expert.skills.length > 0) skillCatalog = skillCatalog.filter((s) => expert.skills.includes(s.name));
    let mcpCatalog = this.d.mcp?.catalog();
    if (mcpCatalog && expert && expert.tools.length > 0) mcpCatalog = mcpCatalog.filter((c) => expert.tools.includes(`mcp:${c.name}`));

    const messages: ChatMessage[] = [{ id: randomUUID(), role: 'user', content: prompt, createdAt: Date.now() }];
    // 子代理内部过程不混入主对话流：error 提为 notice；tool_start 冒泡为 task 卡片实时进度
    const childEmit: Emit = (e) => {
      if (e.type === 'error') {
        parent.emit({ type: 'notice', sessionId, message: `子代理任务出错：${e.message}` });
        return;
      }
      // 带主 task 的 callId → 并行子代理各更新各的卡片，不互相覆盖（避开 notice/权限并行覆盖的坑）
      if (e.type === 'tool_start') {
        parent.emit({ type: 'tool_progress', sessionId, callId: parent.callId, text: `${e.name} ${e.argsSummary}`.trim() });
      }
    };

    await runTurn({
      sessionId,
      messages,
      client: new LlmClient(parent.config),
      config: parent.config,
      bus,
      gate: parent.gate,
      checkpoint: this.d.checkpoint,
      readState: new ReadState(),
      workspace: this.d.workspace.activePath(),
      workspaceRoots: this.d.workspace.rootsList(),
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
        void this.d.usage?.recordUsage({
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
        void this.d.usage?.recordTool({ sessionId, ...r });
      },
    });

    if (signal.aborted) return '（子代理任务已随主任务中断）';
    const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');
    return (lastAssistant?.content || '').trim() || '（子代理未产出结果）';
  }
}
