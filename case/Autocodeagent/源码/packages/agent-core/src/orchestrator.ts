/**
 * Orchestrator（技术方案 §4.1 / AGENTS §13 / P1 任务 4）：
 * runTurn 主循环 maxTurns=200（长任务；上下文窗口管理见 context.ts 两级降级）；
 * tool_calls 流结束后一次性 parse（§17）；
 * 同消息内全 READ 独立调用并发执行；同参连败 2 次熔断；
 * 权限拦截位于循环内、执行前（§14）；WRITE/EXEC 前 checkpoint。
 * 只依赖 ToolBus / PermissionGate / Checkpoint，不硬编码工具分支。
 */
import { randomUUID } from 'node:crypto';
import type { ChatMessage, LlmToolSchema, ModelConfig, NormalizedUsage, Risk, StreamEvent, StoredToolCall, TodoItem } from '@agentbuddy/shared';
import { resolveWithinRoots } from './workspace/workspace';
import { assembleContext, clampOutputTokens, computePromptBudget, estimateTokens, planCompaction, pruneToolsToWindow, renderHistoryForSummary, type McpSummary, type SkillSummary } from './context';
import { primaryTarget, type PermissionGate } from './permission';
import type { Checkpoint } from './checkpoint';
import type { LlmClient } from './llm/client';
import type { ToolBus } from './tools/bus';
import { ReadState, type ToolContext } from './tools/types';
import { TASK_TOOL_NAME } from './tools/taskTool';

/** 单次任务最大轮数（长任务支持；超窗口由 context.ts 两级降级兜底） */
export const MAX_TURNS = 200;
/** 子代理（task）并行上限：一轮派多个 task 时限流，防同时打爆本地推理服务；纯 read 并行不受此限 */
export const PARALLEL_LIMIT = 4;
const TOOL_TIMEOUT_MS = 60_000;
/** length 截断自动续写上限（防无限续写循环） */
const MAX_AUTO_CONTINUE = 3;
const CONTINUE_PROMPT =
  '上一次输出被单轮长度上限截断。请从截断处直接继续写完：不要重复已输出的内容，不要添加解释或过渡语。';
/** 400 探测到的真实上下文窗口（按 baseUrl::model 缓存）：配置 contextWindow 与离线服务实际窗口不一致时自愈 */
const learnedWindows = new Map<string, number>();
const CONTEXT_LENGTH_RE = /maximum context length is (\d+)/i;
/** vLLM 输出上限预检查报错：max_tokens > max_model_len（在处理输入前就 400，与上面的 context length 是两类错误） */
const MAX_MODEL_LEN_RE = /max_model_len\D{0,30}(\d+)/i;
/** 低于此窗口视为「装不下系统提示 + 内置工具 + 最小输出」，给明确换模型提示而非静默降级 */
const MIN_VIABLE_WINDOW = 8192;
/** ③ 摘要压缩：单次最多纳入摘要的消息条数（超出部分下轮滚动处理，防单次摘要请求自身超窗） */
const MAX_COMPACT_MESSAGES_PER_CALL = 30;
/** ③ 摘要压缩的摘要器系统提示：用当前模型产出要点式中文摘要，供后续对话续接（非破坏性，仅进发送视图） */
const SUMMARY_SYSTEM_PROMPT =
  '你是对话历史摘要器。把用户提供的对话片段压缩成简洁的中文要点式摘要，供后续对话继续时快速了解此前进展。' +
  '必须保留：已完成的动作与结论、涉及的文件路径与关键改动、遇到的问题与解决方式、尚未完成的待办、用户的原始意图与约束。' +
  '省略：寒暄、重复内容、大段工具原始输出（只留结论）。直接输出摘要正文，不要加「以下是摘要」之类前缀或解释。';

export type Emit = (event: StreamEvent) => void;

export interface TurnDeps {
  sessionId: string;
  /** 会话 live 消息（含本轮 user 消息） */
  messages: ChatMessage[];
  client: LlmClient;
  config: ModelConfig;
  bus: ToolBus;
  gate: PermissionGate;
  checkpoint: Checkpoint;
  readState: ReadState;
  /** 活动目录（相对路径默认根 / 命令 cwd / git 归属） */
  workspace: string | null;
  /** 多工作区：全部已关联根（jail 与跨根路径解析） */
  workspaceRoots: string[];
  signal: AbortSignal;
  emit: Emit;
  persist: (msg: ChatMessage) => Promise<void>;
  /** 每轮响应结束采集 usage（§4.7） */
  onUsage?: (usage: NormalizedUsage) => void;
  /** P6：每次工具调用终态回调（执行记录 records.jsonl 采集） */
  onRecord?: (record: { tool: string; target: string; risk: Risk; ok: boolean; ms: number }) => void;
  /** P4：④层技能目录（仅启用技能摘要，进系统提示） */
  skillCatalog?: SkillSummary[];
  /** P4：/name 触发的技能正文（当轮高优先级指令） */
  skillInstruction?: string;
  /** P4：todo_write 清单变更持久化（plan 事件由 Loop 统一发出） */
  onTodos?: (todos: TodoItem[]) => void;
  /** P5：⑤层 MCP 连接器目录（仅已连接，# 提及语义） */
  mcpCatalog?: McpSummary[];
  /** P7：专家人设（会话绑定专家时注入系统提示；工具限定由外层构建 bus 时完成） */
  persona?: string;
  /**
   * Phase 2 按需加载·per-session 发现集：跨多次 runTurn 累积已发现的 MCP 工具名，
   * 使整个会话记住 search_tools 命中结果，无需每次提问重复检索。缺省则退化为本次 runTurn 内的临时集。
   */
  discovered?: Set<string>;
  /** P4：会话当前执行计划（todo_write 清单）——注入每轮系统提示，使模型跨中断 / 裁剪后仍知道进度 */
  todos?: TodoItem[];
}

interface ParsedCall {
  call: StoredToolCall;
  input: Record<string, unknown>;
  parseError: string | null;
}

export async function runTurn(dep: TurnDeps): Promise<void> {
  const failures = new Map<string, number>();
  let turns = 0;
  let continues = 0;
  const windowKey = `${dep.config.baseUrl}::${dep.config.model}`;
  let effectiveWindow = learnedWindows.get(windowKey) ?? dep.config.contextWindow;
  let pruneNoticed = false;
  // 按需加载：search_tools 发现的 MCP 工具名累积注入后续每轮 schema（发现与调用分两轮）。
  // dep.discovered 由 chatService 按 sessionId 持有 → per-session 记忆，跨多次提问不必重复检索；缺省退化为本次 runTurn 临时集。
  const discovered = dep.discovered ?? new Set<string>();
  // 执行计划：会话初始清单 + 本轮 todo_write 更新，注入每轮系统提示（跨中断 / 裁剪后模型仍知道进度）。
  // 用可变 holder：execCall 的 onTodos 回填后，下一轮 assembleContext 即读到最新状态。
  const todoState: { items: TodoItem[] } = { items: dep.todos ? [...dep.todos] : [] };

  // ③ LLM 摘要压缩（非破坏性）：历史超预算时用当前模型把最旧消息组摘要成一条，替换进「发送视图」，
  //    把 context.ts 降级 2 的「直接丢」升级为「先总结再丢」；摘要随轮滚动增量复用，调用失败则静默退回原截断兜底。
  //    仅影响发给 LLM 的 wire，dep.messages / 持久化 transcript / UI 均不动（状态为本次 runTurn 局部）。
  let compactFrom = 0; // 已摘要到的 dep.messages 索引（exclusive）；0 = 尚未压缩
  let compactHeadEnd = 0; // 受保护头部条数（首条用户消息）
  let compactSummary = ''; // 滚动累积的摘要正文

  /** 发送给 LLM 的历史视图：压缩后用摘要替换 [headEnd, compactFrom)，其余原样 */
  const historyView = (): ChatMessage[] => {
    if (!compactSummary || compactFrom <= compactHeadEnd) return dep.messages;
    const summaryMsg: ChatMessage = {
      id: 'compaction-summary',
      role: 'user',
      content: `[上下文摘要 · 较早的 ${compactFrom - compactHeadEnd} 条消息已压缩为要点]\n${compactSummary}`,
      createdAt: Date.now(),
    };
    return [...dep.messages.slice(0, compactHeadEnd), summaryMsg, ...dep.messages.slice(compactFrom)];
  };

  /** 发送视图超预算时触发一次增量摘要压缩；失败/不足以摘要则不改动状态，交由 trimToBudget/dropOldMessages 兜底 */
  const compactIfNeeded = async (cfg: ModelConfig, tools: LlmToolSchema[]): Promise<void> => {
    const budget = computePromptBudget(cfg, tools);
    const tokens = historyView().reduce((s, m) => s + estimateTokens(m.content || ''), 0);
    if (tokens <= budget) return;
    const plan = planCompaction(dep.messages, compactFrom);
    if (!plan) return;
    const newStart = Math.max(plan.headEnd, compactFrom);
    const end = Math.min(plan.end, newStart + MAX_COMPACT_MESSAGES_PER_CALL); // 单次上限，超出下轮滚动处理
    const transcript = renderHistoryForSummary(dep.messages, newStart, end);
    if (!transcript.trim()) return;
    const prev = compactSummary ? `已有摘要（请合并进新摘要，勿丢其中关键信息）：\n${compactSummary}\n\n` : '';
    try {
      const res = await dep.client.chat({
        messages: [
          { role: 'system', content: SUMMARY_SYSTEM_PROMPT },
          { role: 'user', content: `${prev}需要摘要的新对话片段：\n${transcript}` },
        ],
        temperature: 0.2,
        maxTokens: 1024,
        signal: dep.signal,
        onDelta: () => {},
      });
      const text = (res.message.content || '').trim();
      if (!text) return; // 空摘要 → 放弃本次压缩
      compactSummary = text;
      compactHeadEnd = plan.headEnd;
      compactFrom = end;
      dep.emit({
        type: 'notice',
        sessionId: dep.sessionId,
        message: `已把较早的 ${compactFrom - compactHeadEnd} 条历史压缩为摘要以节省上下文（会话原始记录仍完整保留）。`,
      });
    } catch {
      // 摘要调用失败（网络/超窗/空响应/中断）：静默退回原截断式兜底，不打断主任务
    }
  };

  while (turns++ < MAX_TURNS) {
    if (dep.signal.aborted) return;

    // 窗口物理容量裁剪：schema 全量下发装不下时按序少挂 MCP 工具（内置恒保留）——溢出与历史无关，新会话同样生效
    // 输出上限也按真实窗口收敛：小窗口模型（vLLM max_model_len）下 max_tokens 不得超过窗口，否则处理输入前即 400
    const cfg: ModelConfig = {
      ...dep.config,
      contextWindow: effectiveWindow,
      maxTokens: clampOutputTokens(dep.config.maxTokens, effectiveWindow),
    };
    // 按需加载：deferred 模式下只下发常驻 + 已发现工具的 schema；无 deferred 时 selectSchemas 等同全量 schemas()
    const { kept: tools, dropped } = pruneToolsToWindow(dep.bus.selectSchemas(discovered), effectiveWindow, cfg.maxTokens);
    if (dropped.length > 0 && !pruneNoticed) {
      pruneNoticed = true;
      dep.emit({
        type: 'notice',
        sessionId: dep.sessionId,
        message: `上下文窗口（${effectiveWindow}）装不下全部工具 schema：本轮少下发 ${dropped.length} 个 MCP 工具。可停用部分连接器，或换用更大上下文窗口的模型。`,
      });
    }
    // ⑤层 MCP 目录：按需（deferred）模式下全量保留作「发现索引」（模型据此知道有哪些连接器，用 search_tools 检索）；
    // 全量常驻模式下与实发 schema 对齐——被窗口裁剪掉的连接器不再进 # 提及目录（避免提及不可用工具）
    let mcpCatalog = dep.mcpCatalog;
    if (!dep.bus.hasDeferred() && mcpCatalog) {
      const keptServers = new Set(
        tools.map((t) => /^mcp__([^_].*?)__/.exec(t.function.name)?.[1]).filter((s): s is string => Boolean(s)),
      );
      mcpCatalog = mcpCatalog.filter((c) => keptServers.has(c.name));
    }
    // ③ 摘要压缩：发送视图超预算则先把最旧消息组摘要替换（升级为「先总结再丢」），再组装本轮上下文
    await compactIfNeeded(cfg, tools);
    if (dep.signal.aborted) return;
    const wire = await assembleContext({
      workspace: dep.workspace,
      extraRoots: dep.workspaceRoots.filter((r) => r !== dep.workspace),
      config: cfg,
      history: historyView(),
      mode: dep.gate.mode,
      skillCatalog: dep.skillCatalog,
      skillInstruction: dep.skillInstruction,
      mcpCatalog,
      persona: dep.persona,
      tools,
      todos: todoState.items,
    });
    const messageId = randomUUID();
    let partial = '';
    let res;
    let retriedWindow = false;
    try {
      res = await dep.client.chat({
        messages: wire,
        tools,
        temperature: dep.config.temperature,
        maxTokens: cfg.maxTokens,
        signal: dep.signal,
        onDelta: (delta) => {
          partial += delta;
          dep.emit({ type: 'token', sessionId: dep.sessionId, messageId, delta });
        },
        // 推理模型思维链：独立 reasoning 事件流出（前端灰色「思考过程」区），不计入 partial / 不落 wire 历史
        onReasoning: (delta) => {
          dep.emit({ type: 'reasoning', sessionId: dep.sessionId, messageId, delta });
        },
      });
    } catch (e) {
      // 上下文/输出超窗 400：从服务端报错探测真实窗口，收敛窗口 + 输出上限后本轮重试一次（配置偏大时自愈）
      const msg = e instanceof Error ? e.message : '';
      const hit = CONTEXT_LENGTH_RE.exec(msg) ?? MAX_MODEL_LEN_RE.exec(msg);
      if (hit && !retriedWindow) {
        retriedWindow = true;
        effectiveWindow = Math.min(effectiveWindow, Number(hit[1]));
        learnedWindows.set(windowKey, effectiveWindow);
        // 窗口过小：裁剪与压缩都救不回，明确提示换模型或调大服务端 --max-model-len（下一轮 clamp 会消掉 max_tokens 报错）
        if (effectiveWindow < MIN_VIABLE_WINDOW) {
          dep.emit({
            type: 'notice',
            sessionId: dep.sessionId,
            message: `检测到模型上下文窗口仅 ${effectiveWindow} tokens，不足以容纳系统提示、内置工具与最小输出（约需 ${MIN_VIABLE_WINDOW}+）。请换用更大窗口的模型，或在推理服务端调大 --max-model-len。`,
          });
        }
        continue;
      }
      // abort：当前半截 assistant 消息标记落盘，不带入下轮请求（§4.1 约束 4）
      if (dep.signal.aborted && partial) {
        const msg: ChatMessage = { id: messageId, role: 'assistant', content: partial, createdAt: Date.now() };
        dep.messages.push(msg);
        await dep.persist(msg);
      }
      throw e;
    }
    dep.onUsage?.(res.usage);

    const hasToolCalls = Boolean(res.toolCalls && res.toolCalls.length > 0);
    // 仅当有正式内容或工具调用时才落盘 assistant：推理模型「只思考未回答」（content 空、reasoning 已 live 展示）
    // 不落盘——避免回放出现空气泡，也避免下一轮 wire 塞入 content='' 的空 assistant 消息
    if (res.message.content || hasToolCalls) {
      const assistant: ChatMessage = {
        id: messageId,
        role: 'assistant',
        content: res.message.content,
        createdAt: Date.now(),
        toolCalls: res.toolCalls,
      };
      dep.messages.push(assistant);
      await dep.persist(assistant);
    }

    // 截断续写：finish=length 且无工具调用 = 纯文本被 max_tokens 截断（用户可见的「输出不完整」根因）。
    // 自动插入续写指令进下一轮（仅 live 消息不落盘：避免回放与 UI 多出指令气泡）；超上限正常收尾。
    if (res.finishReason === 'length' && !hasToolCalls && continues < MAX_AUTO_CONTINUE) {
      continues += 1;
      dep.messages.push({ id: randomUUID(), role: 'user', content: CONTINUE_PROMPT, createdAt: Date.now() });
      continue;
    }

    if (!hasToolCalls) return; // 无工具调用 = 回合结束

    const parsed = res.toolCalls!.map(parseCall); // hasToolCalls===true 已确保 toolCalls 非空
    const allRead = parsed.every((p) => riskOf(dep.bus, p) === 'READ');
    if (allRead && parsed.length > 1) {
      const run = (p: ParsedCall): Promise<boolean> => execCall(dep, p, failures, discovered, todoState);
      if (parsed.some((p) => p.call.name === TASK_TOOL_NAME)) {
        // 含 task（派发子代理）→ 并发池限流 + 检查熔断（防一轮派多个子代理打爆本地推理）
        const tripped = await runPool(parsed, PARALLEL_LIMIT, run);
        if (tripped || dep.signal.aborted) return;
      } else {
        // 纯 read → 全并行（既有行为不变）
        await Promise.all(parsed.map(run));
      }
    } else {
      for (const p of parsed) {
        const tripped = await execCall(dep, p, failures, discovered, todoState);
        if (tripped || dep.signal.aborted) return;
      }
    }
  }
  dep.emit({ type: 'error', sessionId: dep.sessionId, message: `达到 maxTurns（${MAX_TURNS}），任务未完成` });
}

/**
 * 并发池：以 limit 为上限并行执行 fn，全部完成后返回「是否有任一熔断（tripped）」。手写信号量，无新依赖。
 * 用于一轮派发多个 task 子代理时的限流（纯 read 仍走 Promise.all 全并行，不受此限）。
 */
export async function runPool<T>(items: readonly T[], limit: number, fn: (item: T) => Promise<boolean>): Promise<boolean> {
  let idx = 0;
  let tripped = false;
  const worker = async (): Promise<void> => {
    while (idx < items.length) {
      const t = await fn(items[idx++]!);
      if (t) tripped = true;
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return tripped;
}

function parseCall(call: StoredToolCall): ParsedCall {
  try {
    const input = call.arguments.trim() ? JSON.parse(call.arguments) : {};
    if (typeof input !== 'object' || input === null) throw new Error('参数必须为对象');
    return { call, input: input as Record<string, unknown>, parseError: null };
  } catch (e) {
    return { call, input: {}, parseError: e instanceof Error ? e.message : String(e) };
  }
}

function riskOf(bus: ToolBus, p: ParsedCall): Risk {
  const tool = bus.get(p.call.name);
  if (!tool) return 'EXEC';
  return tool.assessRisk?.(p.input) ?? tool.risk;
}

/** 返回 true = 熔断触发，主循环应终止；discovered 为本次 runTurn 的按需加载发现集（search_tools 命中回填）；todoState 为执行计划 holder（todo_write 回填） */
async function execCall(dep: TurnDeps, p: ParsedCall, failures: Map<string, number>, discovered: Set<string>, todoState: { items: TodoItem[] }): Promise<boolean> {
  const { call } = p;
  const tool = dep.bus.get(call.name);
  // P6：风险 / 目标提前计算，执行记录各终态分支共用
  const risk = tool?.assessRisk?.(p.input) ?? tool?.risk ?? 'EXEC';
  const target = primaryTarget(call.name, p.input);
  const rec = (ok: boolean, ms: number): void => dep.onRecord?.({ tool: call.name, target, risk, ok, ms });

  const pushToolMsg = async (content: string, ok: boolean, ms: number, changeId?: string): Promise<void> => {
    const msg: ChatMessage = {
      id: call.id,
      role: 'tool',
      content,
      createdAt: Date.now(),
      toolCallId: call.id,
      toolName: call.name,
      toolArgs: call.arguments,
      toolOk: ok,
      toolMs: ms,
      toolChangeId: changeId,
    };
    dep.messages.push(msg);
    await dep.persist(msg);
    dep.emit({ type: 'tool_result', sessionId: dep.sessionId, callId: call.id, ok, ms, summary: content });
  };

  const fail = async (content: string): Promise<boolean> => {
    const key = `${call.name}:${call.arguments}`;
    const n = (failures.get(key) ?? 0) + 1;
    failures.set(key, n);
    await pushToolMsg(content, false, 0);
    if (n >= 2) {
      dep.emit({ type: 'error', sessionId: dep.sessionId, message: `同一工具同一入参连续失败 ${n} 次，已终止` });
      return true;
    }
    return false;
  };

  if (!tool) {
    rec(false, 0);
    return fail(`未知工具: ${call.name}。可用工具: ${dep.bus.names().join(', ')}`);
  }
  if (p.parseError) {
    rec(false, 0);
    return fail(`工具入参 JSON 非法: ${p.parseError}。请修正参数后重试`);
  }

  // 权限拦截：循环内、执行前（§14）
  const decision = await dep.gate.decide({
    callId: call.id,
    name: call.name,
    risk,
    target,
    detail: target || call.arguments,
  });
  if (!decision.allowed) {
    // 拒绝结构化回灌模型，不计入熔断；模式拒绝（Plan 只读等）与用户拒绝文案差异化
    const reason =
      decision.deniedBy === 'mode'
        ? `当前 ${dep.gate.mode} 模式（只读分析）已拒绝 ${call.name}：请改用 read/glob/grep 等只读工具完成分析，或请用户在盾牌菜单切换权限模式。`
        : '用户拒绝了该操作，请换一种方式或向用户说明。';
    rec(false, 0);
    await pushToolMsg(reason, false, 0);
    return false;
  }

  dep.emit({ type: 'tool_start', sessionId: dep.sessionId, callId: call.id, name: call.name, argsSummary: summarizeArgs(call.arguments), risk });

  const ctx: ToolContext = {
    workspace: dep.workspace,
    signal: dep.signal,
    readState: dep.readState,
    snapshot: (affected) =>
      dep.workspace
        ? dep.checkpoint.snapshot(dep.workspace, affected, randomUUID(), dep.sessionId).then((set) => set?.changeId ?? null)
        : Promise.resolve(null),
    resolvePath: (userPath) =>
      dep.workspace
        ? resolveWithinRoots(dep.workspaceRoots.length > 0 ? dep.workspaceRoots : [dep.workspace], dep.workspace, userPath)
        : Promise.reject(new Error('未选择工作区目录')),
    // todo_write 清单变更：回填 todoState（下一轮 assembleContext 即注入最新计划）+ 由 Loop 发 plan 事件（§18），外层回调仅做落盘等副作用
    onTodos: (todos) => {
      todoState.items = todos;
      dep.emit({ type: 'plan', sessionId: dep.sessionId, todos });
      dep.onTodos?.(todos);
    },
    // 按需加载：search_tools 命中后把工具名记入 discovered，下一轮 selectSchemas 即注入其 schema 供模型调用
    onDiscoverTools: (names) => {
      for (const n of names) discovered.add(n);
    },
  };

  const t0 = Date.now();
  try {
    const out = await withTimeout(tool.execute(ctx, p.input), tool.name === 'bash' ? Number.POSITIVE_INFINITY : TOOL_TIMEOUT_MS);
    rec(true, Date.now() - t0);
    await pushToolMsg(out.text, true, Date.now() - t0, out.change?.changeId);
    // P2：WRITE/EXEC 落盘后通知右栏审阅（§事件驱动）
    if (out.change) {
      dep.emit({ type: 'diff_ready', sessionId: dep.sessionId, callId: call.id, changeId: out.change.changeId });
    }
    return false;
  } catch (e) {
    if (dep.signal.aborted) throw e;
    rec(false, Date.now() - t0);
    return fail(`工具执行失败: ${e instanceof Error ? e.message : String(e)}。请调整参数或改用其他工具。`);
  }
}

function summarizeArgs(args: string): string {
  const oneLine = args.replace(/\s+/g, ' ');
  return oneLine.length > 160 ? `${oneLine.slice(0, 160)}…` : oneLine;
}

async function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  if (!Number.isFinite(ms)) return promise;
  let timer: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`工具超时（${ms / 1000}s）`)), ms);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
