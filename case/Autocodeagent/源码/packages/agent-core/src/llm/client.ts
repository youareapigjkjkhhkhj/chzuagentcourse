/**
 * LLM 客户端（技术方案 §4.4）：
 * OpenAI 兼容 chat/completions 流式调用 + SSE 解析 + 响应归一 + 轻量重试。
 * 不依赖任何框架；AbortSignal 全链路透传。
 */
import type { LlmToolSchema, LlmWireMessage, ModelConfig, NormalizedLLMResponse, NormalizedUsage, StoredToolCall } from '@agentbuddy/shared';
import { applyChunk, createAccumulator, deltaOf, parseSseLine } from './sse';
import { normalizeUsage } from './usage';

export interface LlmRequest {
  messages: LlmWireMessage[];
  /** function calling schema（P1 起下发） */
  tools?: LlmToolSchema[];
  temperature: number;
  maxTokens: number;
  signal: AbortSignal;
  onDelta: (delta: string) => void;
}

const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504]);
const MAX_ATTEMPTS = 3;

export class LlmClient {
  constructor(private readonly config: ModelConfig) {}

  async chat(req: LlmRequest): Promise<NormalizedLLMResponse> {
    let lastError: Error | null = null;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      if (req.signal.aborted) throw abortError();
      try {
        return await this.chatOnce(req);
      } catch (e) {
        lastError = e instanceof Error ? e : new Error(String(e));
        if (!isRetryable(lastError) || attempt === MAX_ATTEMPTS || req.signal.aborted) throw lastError;
        await sleep(500 * 2 ** (attempt - 1), req.signal);
      }
    }
    throw lastError ?? new Error('LLM 调用失败');
  }

  private async chatOnce(req: LlmRequest): Promise<NormalizedLLMResponse> {
    const url = `${this.config.baseUrl.replace(/\/$/, '')}/chat/completions`;
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${this.config.apiKey}`,
      },
      body: JSON.stringify(buildBody(this.config, req)),
      signal: req.signal,
    });

    if (!res.ok) throw await httpError(res);
    if (!res.body) throw new Error('LLM 响应缺少 body');

    const acc = createAccumulator();
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { lines, rest } = splitLines(buffer);
      buffer = rest;
      for (const line of lines) {
        const parsed = parseSseLine(line);
        if (parsed.kind === 'done') break;
        if (parsed.kind !== 'data') continue;
        emitDelta(parsed.json, req.onDelta);
        applyChunk(acc, parsed.json);
      }
    }

    if (acc.content === '' && acc.toolCalls.size === 0) {
      throw new Error('LLM 未返回任何内容');
    }

    return buildResponse(acc.content, collectToolCalls(acc), acc.finishReason, acc.usage ? normalizeUsage(acc.usage) : null);
  }
}

/** gpt-5 / o 系列：temperature 仅默认值、max_tokens 需换 max_completion_tokens（厂商归一，§4.4） */
function isReasoningFamily(model: string): boolean {
  return /^(gpt-5|o1|o3|o4)/i.test(model);
}

function buildBody(config: ModelConfig, req: LlmRequest): Record<string, unknown> {
  const body: Record<string, unknown> = {
    model: config.model,
    messages: req.messages,
    stream: true,
    stream_options: { include_usage: true },
  };
  if (req.tools?.length) body.tools = req.tools;
  if (isReasoningFamily(config.model)) {
    body.max_completion_tokens = req.maxTokens;
  } else {
    body.temperature = req.temperature;
    body.max_tokens = req.maxTokens;
  }
  return body;
}

/** §17：流结束后按 index 排序、一次性产出 StoredToolCall（arguments 保留原始串） */
function collectToolCalls(acc: ReturnType<typeof createAccumulator>): StoredToolCall[] | undefined {
  if (acc.toolCalls.size === 0) return undefined;
  return [...acc.toolCalls.values()]
    .sort((a, b) => a.index - b.index)
    .map((tc) => ({ id: tc.id, name: tc.name, arguments: tc.arguments }));
}

/** 从 chunk 提取文本增量并回调（与 applyChunk 分离，保持 sse.ts 纯函数） */
function emitDelta(json: unknown, onDelta: (d: string) => void): void {
  const delta = deltaOf(json);
  if (delta && typeof delta['content'] === 'string' && delta['content']) onDelta(delta['content']);
}

function splitLines(buffer: string): { lines: string[]; rest: string } {
  const parts = buffer.split('\n');
  const rest = parts.pop() ?? '';
  return { lines: parts, rest };
}

function buildResponse(
  content: string,
  toolCalls: StoredToolCall[] | undefined,
  finishReason: string | null,
  usage: NormalizedUsage | null,
): NormalizedLLMResponse {
  return {
    message: { id: '', role: 'assistant', content, createdAt: Date.now() },
    toolCalls,
    usage: usage ?? { promptTokens: 0, completionTokens: 0, totalTokens: 0, cacheReadTokens: 0 },
    finishReason: mapFinish(finishReason),
  };
}

function mapFinish(reason: string | null): NormalizedLLMResponse['finishReason'] {
  if (reason === 'stop' || reason === 'length' || reason === 'tool_calls' || reason === 'content_filter') return reason;
  return 'unknown';
}

class HttpError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

export async function httpError(res: Response): Promise<Error> {
  // 4xx/5xx 响应体通常带服务端的具体原因（OpenAI/vLLM 的 {"error":{"message":…}}），
  // 只看 statusText 会丢掉根因（如 vLLM「maximum context length is N tokens」），必须读出附加
  const detail = await readErrorDetail(res);
  // 401 鉴权失败时附排查提示（最常见原因：Key 复制不完整，如漏了 sk- 前缀）
  const hint = res.status === 401 ? '，请检查 API Key 是否完整（常见：漏复制了 sk- 前缀）或已过期' : '';
  return new HttpError(res.status, `LLM 接口错误 ${res.status}${res.statusText ? `: ${res.statusText}` : ''}${hint}${detail ? ` — ${detail}` : ''}`);
}

/** 从错误响应体提取可读原因：优先 JSON 的 error.message / message，否则原始文本；截断 400 字防刷屏 */
async function readErrorDetail(res: Response): Promise<string> {
  let text = '';
  try {
    text = await res.text();
  } catch {
    return ''; // body 读取失败不影响主错误
  }
  const flat = text.replace(/\s+/g, ' ').trim();
  if (!flat) return '';
  try {
    const json = JSON.parse(flat) as { error?: { message?: unknown }; message?: unknown };
    const msg = json.error?.message ?? json.message;
    if (typeof msg === 'string' && msg.trim()) return msg.trim().slice(0, 400);
  } catch {
    /* 非 JSON body（如代理返回的 HTML 错误页）：回退原始文本 */
  }
  return flat.slice(0, 400);
}

function isRetryable(e: Error): boolean {
  if (e.name === 'AbortError' || e.name === 'TimeoutError') return false;
  if (e instanceof HttpError) return RETRYABLE_STATUS.has(e.status);
  return e.name === 'TypeError' || /fetch failed|network|ECONN/i.test(e.message);
}

function abortError(): Error {
  const e = new Error('已取消');
  e.name = 'AbortError';
  return e;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener('abort', () => { clearTimeout(t); reject(abortError()); }, { once: true });
  });
}

export { normalizeUsage };
