/** LlmClient 健壮性：推理模型 reasoning_content 流出、真空响应自动重试、content_filter 不重试、流末尾 flush 补片。
 *  这些是「模型可连接却偶发『LLM 未返回任何内容』」的根因回归。 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LlmClient } from '../src/llm/client';
import type { LlmWireMessage, ModelConfig } from '@agentbuddy/shared';

const cfg: ModelConfig = {
  id: 'm1', name: 'test', provider: 'vllm', baseUrl: 'http://x/v1', model: 'deepseek-r1',
  apiKey: 'k', encrypted: false, temperature: 0.7, maxTokens: 1024, contextWindow: 32768,
};

const messages: LlmWireMessage[] = [{ role: 'user', content: 'hi' }];

/** 把给定 SSE 文本按块吐出的 Response（每次调用生成新流，供重试复用） */
function sse(chunks: string[]): Response {
  const enc = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(c) { for (const ch of chunks) c.enqueue(enc.encode(ch)); c.close(); },
  });
  return new Response(stream, { status: 200 });
}

function req(over: Partial<Parameters<LlmClient['chat']>[0]> = {}): Parameters<LlmClient['chat']>[0] {
  return {
    messages, temperature: 0.7, maxTokens: 1024,
    signal: new AbortController().signal,
    onDelta: () => {},
    ...over,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe('LlmClient reasoning_content 与空响应健壮性', () => {
  it('reasoning_content 走 onReasoning、content 走 onDelta，互不混淆', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sse([
      'data: {"choices":[{"delta":{"reasoning_content":"思考A"}}]}\n\n',
      'data: {"choices":[{"delta":{"reasoning_content":"思考B"}}]}\n\n',
      'data: {"choices":[{"delta":{"content":"回答"}}]}\n\n',
      'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
      'data: [DONE]\n\n',
    ])));
    let text = '', reasoning = '';
    const res = await new LlmClient(cfg).chat(req({
      onDelta: (d) => { text += d; },
      onReasoning: (d) => { reasoning += d; },
    }));
    expect(reasoning).toBe('思考A思考B');
    expect(text).toBe('回答');
    expect(res.message.content).toBe('回答');
    expect(res.finishReason).toBe('stop');
  });

  it('content 空但有 reasoning（推理模型只思考）：不抛「未返回内容」，返回空 content', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sse([
      'data: {"choices":[{"delta":{"reasoning_content":"我在思考"}}]}\n\n',
      'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
      'data: [DONE]\n\n',
    ])));
    let reasoning = '';
    const res = await new LlmClient(cfg).chat(req({ onReasoning: (d) => { reasoning += d; } }));
    expect(reasoning).toBe('我在思考');
    expect(res.message.content).toBe('');
    expect(res.finishReason).toBe('stop');
  });

  it('真空响应首次为空 → 自动重试后成功', async () => {
    let i = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      i += 1;
      return i === 1
        ? sse(['data: {"choices":[{"delta":{},"finish_reason":null}]}\n\n', 'data: [DONE]\n\n'])
        : sse(['data: {"choices":[{"delta":{"content":"重试成功"}}]}\n\n', 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n', 'data: [DONE]\n\n']);
    }));
    const res = await new LlmClient(cfg).chat(req());
    expect(res.message.content).toBe('重试成功');
    expect(i).toBe(2);
  });

  it('真空响应持续：重试至上限（3 次）后抛错', async () => {
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => { calls += 1; return sse(['data: [DONE]\n\n']); }));
    await expect(new LlmClient(cfg).chat(req())).rejects.toThrow(/未返回任何内容/);
    expect(calls).toBe(3);
  });

  it('content_filter 空响应：明确拦截不重试（仅 1 次），错误含 content_filter', async () => {
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls += 1;
      return sse(['data: {"choices":[{"delta":{},"finish_reason":"content_filter"}]}\n\n', 'data: [DONE]\n\n']);
    }));
    await expect(new LlmClient(cfg).chat(req())).rejects.toThrow(/content_filter/);
    expect(calls).toBe(1);
  });

  it('流末尾无换行的最后一片：done 后 flush 补处理，不丢内容', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sse([
      'data: {"choices":[{"delta":{"content":"前半"}}]}\n\n',
      'data: {"choices":[{"delta":{"content":"后半"}}]}', // 无尾随换行、无 [DONE]
    ])));
    let text = '';
    const res = await new LlmClient(cfg).chat(req({ onDelta: (d) => { text += d; } }));
    expect(res.message.content).toBe('前半后半');
    expect(text).toBe('前半后半');
  });
});
