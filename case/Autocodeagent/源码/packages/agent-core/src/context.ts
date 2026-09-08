/**
 * 上下文组装与 token 预算（技术方案 §4.3 / P1 任务 8 截断版）。
 * 注入顺序固定六层（P1 实现 ①②③⑥，P4 补齐 ④ Skills 目录）；
 * 预算 = contextWindow − 8k；两级降级：
 * ① 旧工具结果替换为占位摘要（保留首 10 行）；
 * ② 仍超限则按「assistant(tool_calls)+对应 tool 结果」成组从最旧丢弃
 *    （保 system / 首条用户消息 / 最近尾部），支撑 200 轮长任务；
 * 系统区永不裁剪；Compaction（调小模型摘要）留后续阶段。
 */
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { ChatMessage, LlmToolSchema, LlmWireMessage, ModelConfig, PermissionMode } from '@agentbuddy/shared';

export const OUTPUT_RESERVE = 8000;
const PROJECT_INSTRUCTION_LIMIT = 8000;
/** 保留最近 N 条工具结果不压缩 */
const KEEP_RECENT_TOOL_RESULTS = 3;
/** 降级 2 保留最近 N 条消息不丢弃（约最近 6 组调用） */
const KEEP_TAIL_MESSAGES = 12;

/** P3：模式约束前置注入——让模型按当前权限模式规划，而非「先尝试再被拒」 */
const MODE_PROMPT: Record<PermissionMode, string> = {
  Plan: '当前权限模式 Plan（只读分析）：仅 read/glob/grep 等只读工具可用，edit/write/bash 会被直接拒绝。请直接完成分析并给出可执行计划，不要尝试任何写操作。',
  Ask: '当前权限模式 Ask：写/执行类操作会逐次询问用户确认，可正常规划调用，等待确认结果即可。',
  Auto: '当前权限模式 Auto：读取、工作区内写入与白名单低风险命令自动执行；高风险或非白名单操作仍会询问用户。',
};

/** P0：CJK/全角/假名/谚文等宽字符 ≈0.7 token/字（length/4 对中文低估约 2.5 倍，降级触发过晚），其余 ≈0.25（= 原基线） */
const WIDE_CHAR_RE = /[\u2E80-\u9FFF\uAC00-\uD7AF\uF900-\uFAFF\uFF00-\uFFEF]/g;
export function estimateTokens(text: string): number {
  const wide = (text.match(WIDE_CHAR_RE) ?? []).length;
  return Math.ceil(wide * 0.7 + (text.length - wide) * 0.25);
}

export function toWire(m: ChatMessage): LlmWireMessage {
  if (m.role === 'assistant') {
    const wire: LlmWireMessage = { role: 'assistant', content: m.content || null };
    if (m.toolCalls?.length) {
      wire.tool_calls = m.toolCalls.map((tc) => ({
        id: tc.id,
        type: 'function',
        function: { name: tc.name, arguments: tc.arguments },
      }));
    }
    return wire;
  }
  if (m.role === 'tool') return { role: 'tool', content: m.content, tool_call_id: m.toolCallId ?? m.id };
  return { role: m.role, content: m.content };
}

export interface SkillSummary {
  name: string;
  description: string;
}

/** P5：⑤层 MCP 连接器目录（仅已连接，# 提及语义） */
export interface McpSummary {
  name: string;
  description: string;
  tools: string[];
}

export function systemPrompt(
  workspace: string | null,
  model: string,
  instructions: string | null,
  mode: PermissionMode = 'Ask',
  skillCatalog?: SkillSummary[],
  skillInstruction?: string,
  mcpCatalog?: McpSummary[],
  extraRoots?: string[],
  persona?: string,
  webTools?: { fetch: boolean; search: boolean },
): string {
  const parts = [
    '你是 AgentBuddy，本地轻量的通用 AI 助理。通过工具操作用户工作区的文件与命令，覆盖办公文档、资料整理、日常问答与编程开发等多种任务。',
    '回复语言：始终与用户当前消息使用相同的语言（中文提问用中文回复，英文提问用英文回复），除非用户明确要求切换语言。',
    '通用任务（办公文档 / 资料整理 / 报告表格 PPT / 日常问答等）：先用 read、glob 摸清工作区已有素材，再用 write、edit 产出或修改文件，必要时用 bash 运行脚本或命令做格式转换与批量处理；产出文件后回读确认结果符合预期，不要只在回复里描述而不落盘。',
    '安全约束：所有文件操作仅限工作区内；写与执行类操作需经用户权限确认；工具失败时调整参数或换用其他工具，不要重复同样的失败调用。',
    MODE_PROMPT[mode],
    `当前模型：${model}；运行平台：${process.platform}。`,
    workspace
      ? `工作区路径：${workspace}${extraRoots?.length ? `（多工作区：另关联 ${extraRoots.join('、')}，其中文件以「目录名/相对路径」形式出现在 @ 菜单与文件树中）` : ''}`
      : '尚未选择工作区：文件与命令工具不可用，请先提示用户选择工作区。',
    '提及语法：用户消息中 @路径 提及工作区文件或文件夹（处理前优先 read 被提及的文件、用 glob 浏览被提及的文件夹）；#连接器名 提及 MCP 连接器；/技能名 触发技能。',
  ];
  if (instructions) parts.push(`项目指令（AGENTS.md）：\n${instructions}`);
  // ④ Skills 目录：仅 name+description 摘要，正文不进上下文；模型任务匹配时主动 use_skill 自取（渐进披露）
  if (skillCatalog?.length) {
    parts.push(`可用技能（任务与某技能描述匹配时，主动调用 use_skill 工具加载其正文并严格遵循，无需等待用户触发；用户也可用 /技能名 手动触发）：\n${skillCatalog.map((s) => `- /${s.name}：${s.description}`).join('\n')}`);
  }
  // /name 触发：正文作为当轮高优先级指令（仅本轮，不落历史）
  if (skillInstruction) parts.push(`高优先级指令（用户触发的技能正文，请严格遵循）：\n${skillInstruction}`);
  // ⑤ MCP 连接器目录：#名称 提及即优先使用该连接器工具（P5）
  if (mcpCatalog?.length) {
    const lines = mcpCatalog.map((s) => {
      const shown = s.tools.slice(0, 10).join(', ');
      const more = s.tools.length > 10 ? ` 等 ${s.tools.length} 个` : '';
      return `- #${s.name}${s.description ? `：${s.description}` : ''}（工具：${shown}${more}）`;
    });
    parts.push(`已连接 MCP 连接器（用户消息中用 #名称 提及时优先使用对应连接器）：\n${lines.join('\n')}`);
  }
  // 联网能力说明：按本轮实际下发的 web 工具（源自 bus.schemas）措辞，绝不提及不可用的工具
  if (webTools?.fetch || webTools?.search) {
    const caps: string[] = [];
    if (webTools.search) caps.push('需要实时/最新信息（新闻、时效问答、在线文档、价格等本地知识不足）时用 websearch 联网搜索');
    if (webTools.fetch) caps.push('需要阅读某个网页正文时用 webfetch 抓取（返回纯文本，无法执行页面 JS）');
    parts.push(`联网能力：${caps.join('；')}。联网为受控操作，会按当前权限模式请求确认。`);
  }
  // P7 专家人设：会话绑定专家时追加（工具/技能限定已在总线与目录层生效，此处只注入人设正文）
  if (persona) parts.push(`专家人设（本会话绑定专家，请以该身份回复并优先使用已绑定的工具与技能）：\n${persona}`);
  return parts.join('\n');
}

export async function assembleContext(opts: {
  workspace: string | null;
  /** 多工作区：除活动目录外的其他关联根（进系统提示） */
  extraRoots?: string[];
  config: ModelConfig;
  history: ChatMessage[];
  /** P3：当前权限模式（每轮由 gate 提供） */
  mode?: PermissionMode;
  /** P4：④层技能目录（仅启用技能摘要） */
  skillCatalog?: SkillSummary[];
  /** P4：/name 触发的技能正文（当轮高优先级指令） */
  skillInstruction?: string;
  /** P5：⑤层 MCP 连接器目录（仅已连接） */
  mcpCatalog?: McpSummary[];
  /** P7：专家人设（会话绑定专家时注入系统提示） */
  persona?: string;
  /** function-calling schema：序列化后也占 prompt token（后端把它渲染进系统区），须计入预算，
   * 否则消息 trim 到预算内、加上 schema 后仍会超窗 → 400「maximum context length」（离线 vLLM 常见） */
  tools?: LlmToolSchema[];
}): Promise<LlmWireMessage[]> {
  const instructions = opts.workspace ? await readProjectInstructions(opts.workspace) : null;
  // 联网提示按实际下发的 schema 推导（webfetch 内置常驻、websearch 配置后注入），避免提及不可用工具
  const toolNames = new Set((opts.tools ?? []).map((t) => t.function.name));
  const webTools = { fetch: toolNames.has('webfetch'), search: toolNames.has('websearch') };
  const wire: LlmWireMessage[] = [
    {
      role: 'system',
      content: systemPrompt(opts.workspace, opts.config.model, instructions, opts.mode ?? 'Ask', opts.skillCatalog, opts.skillInstruction, opts.mcpCatalog, opts.extraRoots, opts.persona, webTools),
    },
    ...opts.history.map(toWire),
  ];
  trimToBudget(wire, computePromptBudget(opts.config, opts.tools));
  return wire;
}

/**
 * 本轮 prompt 的 token 预算 = contextWindow − 输出预留 − 工具 schema 估算，再留 5% 估算误差余量。
 * - 输出预留 max(OUTPUT_RESERVE, maxTokens)：至少 8k 安全垫，maxTokens 更大时按实际输出上限；
 * - 工具 schema 此前完全未计入，是「消息已 trim 仍超窗」的主因（后端把 tools 渲染进 prompt）；
 * - estimateTokens 是字符近似：未计 chat-template 每条消息的 role/特殊 token，且对 JSON schema /
 *   代码 / 英文技术文本低估真实 BPE 计数 → 乘 0.95 留余量，避免「估算刚好卡线、真实却超窗」的 400；
 * - 下限 4000 兜底，窗口极小时也不至于把预算算成 0/负数。
 */
export function computePromptBudget(config: ModelConfig, tools?: LlmToolSchema[]): number {
  const reserve = Math.max(OUTPUT_RESERVE, config.maxTokens);
  const toolsTokens = tools?.length ? estimateTokens(JSON.stringify(tools)) : 0;
  return Math.max(4000, Math.floor((config.contextWindow - reserve - toolsTokens) * 0.95));
}

/** JSON schema / 代码类 ASCII 文本真实 BPE 约 0.3~0.4 token/字符，estimateTokens 的 0.25 系数会低估 → 专用保守系数 */
const SCHEMA_TOKEN_PER_CHAR = 0.35;
/** 系统提示 token 预留上界（六层注入实际约 2~3k，留余量防卡线） */
const SYSTEM_PROMPT_ALLOWANCE = 4000;
/** 消息区最低保障：与 computePromptBudget 的 4000 下限同源，保证裁剪后仍有对话空间 */
const MIN_MESSAGE_ROOM = 4000;

/** 工具 schema 序列化后的保守 token 估算（后端把 tools 渲染进 prompt，JSON 文本按 0.35/字符计） */
export function estimateSchemaTokens(payload: unknown): number {
  return Math.ceil(JSON.stringify(payload).length * SCHEMA_TOKEN_PER_CHAR);
}

/**
 * 上下文窗口的物理约束：schema 随每次请求全量下发，窗口装不下时消息裁剪无能为力（新会话也会 400）。
 * 按插入顺序保留 MCP 工具（挂载名 mcp__server__tool），内置工具恒保留；返回被跳过工具名供上层提示。
 * 容量 = 窗口 − 输出预留 − 系统提示预留 − 消息最低保障 − 内置 schema；只认真实窗口，与配置写多大无关。
 */
export function pruneToolsToWindow(
  tools: LlmToolSchema[],
  windowTokens: number,
  maxTokens: number,
): { kept: LlmToolSchema[]; dropped: string[] } {
  const reserve = Math.max(OUTPUT_RESERVE, maxTokens);
  let room = windowTokens - reserve - SYSTEM_PROMPT_ALLOWANCE - MIN_MESSAGE_ROOM;
  const kept: LlmToolSchema[] = [];
  const dropped: string[] = [];
  for (const t of tools) {
    const cost = estimateSchemaTokens(t);
    // 内置恒保留（仍占用容量）；MCP 按序装入，装不下的跳过
    if (!t.function.name.startsWith('mcp__')) {
      kept.push(t);
      room -= cost;
      continue;
    }
    if (room >= cost) {
      kept.push(t);
      room -= cost;
    } else {
      dropped.push(t.function.name);
    }
  }
  return { kept, dropped };
}

/** 超限降级 1：旧工具结果正文 → 占位摘要（保留首 10 行）；系统区与最近结果不动 */
export function trimToBudget(wire: LlmWireMessage[], budget: number): void {
  let total = wire.reduce((sum, m) => sum + estimateTokens(m.content ?? ''), 0);
  if (total <= budget) return;

  const toolIndexes: number[] = [];
  wire.forEach((m, i) => {
    if (m.role === 'tool') toolIndexes.push(i);
  });
  const compactable = toolIndexes.slice(0, Math.max(0, toolIndexes.length - KEEP_RECENT_TOOL_RESULTS));

  for (const i of compactable) {
    if (total <= budget) return;
    const content = wire[i]!.content ?? '';
    if (content.startsWith('[已压缩')) continue;
    const placeholder = compactPlaceholder(content);
    total += estimateTokens(placeholder) - estimateTokens(content);
    const prev = wire[i]!;
    wire[i] = { ...prev, content: placeholder };
  }

  // 降级 2：压缩后仍超限 → 成组丢弃旧消息（支撑 200 轮长任务）
  dropOldMessages(wire, budget);
}

/**
 * 超限降级 2：从最旧起按「消息组」丢弃——
 * assistant(tool_calls) 与其后的 tool 结果成组移除（保证 OpenAI 系 API 的配对约束），
 * 其余单条移除；保留 system、首条用户消息（任务定义）与最近尾部；
 * 有丢弃时在断点插入提示，避免模型误以为从未执行过被丢弃的步骤。
 */
export function dropOldMessages(wire: LlmWireMessage[], budget: number): void {
  let total = wire.reduce((sum, m) => sum + estimateTokens(m.content ?? ''), 0);
  if (total <= budget) return;

  // 尾部保护边界：最近 N 条；若边界落在 tool 消息上，回退纳入发起它的 assistant（配对完整）
  let tailStart = Math.max(1, wire.length - KEEP_TAIL_MESSAGES);
  while (tailStart > 1 && wire[tailStart]?.role === 'tool') tailStart--;

  // 头部保护：system(0) + 首条用户消息（任务定义）
  let headEnd = 1;
  if (wire[1]?.role === 'user') headEnd = 2;

  let dropped = 0;
  let markerAt = -1;
  let i = headEnd;
  while (total > budget && i < tailStart) {
    const m = wire[i]!;
    let unitEnd = i + 1;
    if (m.role === 'assistant' && m.tool_calls?.length) {
      while (unitEnd < wire.length && wire[unitEnd]?.role === 'tool') unitEnd++;
    }
    if (unitEnd > tailStart) break; // 组跨到保护尾部 → 停止（压缩阶段已尽力）
    for (let k = i; k < unitEnd; k++) total -= estimateTokens(wire[k]!.content ?? '');
    wire.splice(i, unitEnd - i);
    tailStart -= unitEnd - i;
    dropped += unitEnd - i;
    if (markerAt < 0) markerAt = i;
  }

  if (dropped > 0 && markerAt >= 0) {
    wire.splice(markerAt, 0, {
      role: 'user',
      content: `[上下文管理：因 token 预算限制，较早的 ${dropped} 条消息已省略（工具结果此前已压缩为摘要）。请基于最近上下文继续任务，不要重复已完成的步骤。]`,
    });
  }
}

export function compactPlaceholder(content: string): string {
  const head = content.split('\n').slice(0, 10).join('\n');
  return `[已压缩 · 原文 ${content.length} 字符，保留首 10 行]\n${head}`;
}

/** ③ 项目指令：AGENTS.md / CLAUDE.md / .cursor/rules 只取其一 */
async function readProjectInstructions(workspace: string): Promise<string | null> {
  const candidates = [join(workspace, 'AGENTS.md'), join(workspace, 'CLAUDE.md'), join(workspace, '.cursor', 'rules')];
  for (const file of candidates) {
    const raw = await readFile(file, 'utf-8').catch(() => null);
    if (raw !== null) return raw.length > PROJECT_INSTRUCTION_LIMIT ? `${raw.slice(0, PROJECT_INSTRUCTION_LIMIT)}\n…（指令过长已截断）` : raw;
  }
  return null;
}
