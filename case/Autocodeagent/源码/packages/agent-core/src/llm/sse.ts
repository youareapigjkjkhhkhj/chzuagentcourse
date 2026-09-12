/**
 * SSE 行解析（技术方案 §4.4 / AGENTS §17）：
 * 只在行级处理 [DONE] 与 data: 前缀；tool_calls.arguments 按 index 累积，
 * 由 client 在流结束后整体 JSON.parse，禁止逐 chunk 解析。
 */
export interface AccumulatedToolCall {
  index: number;
  id: string;
  name: string;
  arguments: string;
}

export interface StreamAccumulator {
  content: string;
  /** 推理模型思维链（delta.reasoning_content）：与 content 分离累积，判空与展示都用 */
  reasoning: string;
  toolCalls: Map<number, AccumulatedToolCall>;
  finishReason: string | null;
  /** 厂商原始 usage，由 client 收尾时经 normalizeUsage 归一 */
  usage: unknown;
}

export function createAccumulator(): StreamAccumulator {
  return { content: '', reasoning: '', toolCalls: new Map(), finishReason: null, usage: null };
}

export type SseLine =
  | { kind: 'done' }
  | { kind: 'data'; json: unknown }
  | { kind: 'skip' };

/** 逐行解析 SSE：data: 前缀剥离、[DONE] 识别、空行与注释忽略 */
export function parseSseLine(line: string): SseLine {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith(':')) return { kind: 'skip' };
  if (!trimmed.startsWith('data:')) return { kind: 'skip' };
  const payload = trimmed.slice(5).trim();
  if (payload === '[DONE]') return { kind: 'done' };
  try {
    return { kind: 'data', json: JSON.parse(payload) };
  } catch {
    return { kind: 'skip' }; // 非法 JSON 行：跳过，不让单行毁掉整流
  }
}

/** 提取 chunk 的 delta 对象：OpenAI 族在 choices[0].delta，兼容顶层 delta */
export function deltaOf(chunk: unknown): Record<string, unknown> | undefined {
  if (typeof chunk !== 'object' || chunk === null) return undefined;
  const c = chunk as Record<string, unknown>;
  const choices = c['choices'];
  if (Array.isArray(choices) && choices.length > 0 && typeof choices[0] === 'object' && choices[0] !== null) {
    const choice = choices[0] as Record<string, unknown>;
    if (typeof choice['delta'] === 'object' && choice['delta'] !== null) return choice['delta'] as Record<string, unknown>;
  }
  if (typeof c['delta'] === 'object' && c['delta'] !== null) return c['delta'] as Record<string, unknown>;
  return undefined;
}

/** 提取 chunk 的思维链增量（reasoning_content，兼容 reasoning 别名）；无则空串 */
export function reasoningDeltaOf(chunk: unknown): string {
  const delta = deltaOf(chunk);
  if (!delta) return '';
  const rc = delta['reasoning_content'] ?? delta['reasoning'];
  return typeof rc === 'string' ? rc : '';
}

/** 提取 chunk 的 finish_reason：优先 choices[0]，兼容顶层 */
export function finishReasonOf(chunk: unknown): string | null {
  if (typeof chunk !== 'object' || chunk === null) return null;
  const c = chunk as Record<string, unknown>;
  const choices = c['choices'];
  if (Array.isArray(choices) && choices.length > 0 && typeof choices[0] === 'object' && choices[0] !== null) {
    const fr = (choices[0] as Record<string, unknown>)['finish_reason'];
    if (typeof fr === 'string') return fr;
  }
  return typeof c['finish_reason'] === 'string' ? (c['finish_reason'] as string) : null;
}

/** 将单个 chunk 合并进累积器；content 增量、usage/finish 取最后出现的值 */
export function applyChunk(acc: StreamAccumulator, chunk: unknown): void {
  if (typeof chunk !== 'object' || chunk === null) return;
  const c = chunk as Record<string, unknown>;

  const delta = deltaOf(chunk);
  if (delta && typeof delta['content'] === 'string') acc.content += delta['content'];
  // 推理模型思维链：DeepSeek-R1 / QwQ / Qwen3-thinking / vLLM 走 delta.reasoning_content（兼容 reasoning 别名）
  acc.reasoning += reasoningDeltaOf(chunk);

  const finish = finishReasonOf(chunk);
  if (finish !== null) acc.finishReason = finish;
  if (c['usage'] && typeof c['usage'] === 'object') acc.usage = c['usage'];

  const calls = delta?.['tool_calls'];
  if (!Array.isArray(calls)) return;
  for (const raw of calls) {
    if (typeof raw !== 'object' || raw === null) continue;
    const tc = raw as Record<string, unknown>;
    const index = typeof tc['index'] === 'number' ? tc['index'] : 0;
    const acc1 = acc.toolCalls.get(index) ?? { index, id: '', name: '', arguments: '' };
    if (typeof tc['id'] === 'string') acc1.id = tc['id'];
    const fn = tc['function'] as Record<string, unknown> | undefined;
    if (fn) {
      if (typeof fn['name'] === 'string' && fn['name']) acc1.name = fn['name'];
      if (typeof fn['arguments'] === 'string') acc1.arguments += fn['arguments'];
    }
    acc.toolCalls.set(index, acc1);
  }
}
