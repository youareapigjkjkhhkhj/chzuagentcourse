import { describe, expect, it } from 'vitest';
import { applyChunk, createAccumulator, parseSseLine } from '../src/llm/sse';

describe('parseSseLine', () => {
  it('解析 data 行', () => {
    const r = parseSseLine('data: {"delta":{"content":"hi"}}');
    expect(r.kind).toBe('data');
  });

  it('识别 [DONE]', () => {
    expect(parseSseLine('data: [DONE]').kind).toBe('done');
  });

  it('跳过空行 / 注释 / 非法 JSON（不让单行毁掉整流）', () => {
    expect(parseSseLine('').kind).toBe('skip');
    expect(parseSseLine(': keep-alive').kind).toBe('skip');
    expect(parseSseLine('data: {broken').kind).toBe('skip');
  });
});

describe('applyChunk', () => {
  it('累积 content 增量', () => {
    const acc = createAccumulator();
    applyChunk(acc, { delta: { content: '你' } });
    applyChunk(acc, { delta: { content: '好' } });
    expect(acc.content).toBe('你好');
  });

  it('tool_calls 按 index 跨 chunk 累积 arguments（禁止逐 chunk JSON.parse）', () => {
    const acc = createAccumulator();
    applyChunk(acc, { delta: { tool_calls: [{ index: 0, id: 'c1', function: { name: 'read', arguments: '{"pa' } }] } });
    applyChunk(acc, { delta: { tool_calls: [{ index: 0, function: { arguments: 'th":"a.ts"}' } }] } });
    applyChunk(acc, { delta: { tool_calls: [{ index: 1, id: 'c2', function: { name: 'grep', arguments: '{}' } }] } });

    expect(acc.toolCalls.size).toBe(2);
    const call0 = acc.toolCalls.get(0);
    expect(call0?.name).toBe('read');
    expect(JSON.parse(call0!.arguments)).toEqual({ path: 'a.ts' });
    expect(acc.toolCalls.get(1)?.name).toBe('grep');
  });

  it('finish_reason 与 usage 取最后出现的值', () => {
    const acc = createAccumulator();
    applyChunk(acc, { finish_reason: null, usage: { prompt_tokens: 1 } });
    applyChunk(acc, { finish_reason: 'stop', usage: { prompt_tokens: 10, completion_tokens: 5 } });
    expect(acc.finishReason).toBe('stop');
    expect((acc.usage as { completion_tokens: number }).completion_tokens).toBe(5);
  });

  it('忽略非法 chunk 不抛错', () => {
    const acc = createAccumulator();
    applyChunk(acc, null);
    applyChunk(acc, 'garbage');
    applyChunk(acc, { delta: { tool_calls: 'not-array' } });
    expect(acc.content).toBe('');
  });

  it('OpenAI 族包裹格式：choices[0].delta / choices[0].finish_reason', () => {
    const acc = createAccumulator();
    applyChunk(acc, { choices: [{ index: 0, delta: { content: 'hello' }, finish_reason: null }] });
    applyChunk(acc, { choices: [{ index: 0, delta: { tool_calls: [{ index: 0, id: 'c1', function: { name: 'read', arguments: '{"path":"a"}' } }] }, finish_reason: null }] });
    applyChunk(acc, { choices: [{ index: 0, delta: {}, finish_reason: 'tool_calls' }], usage: { prompt_tokens: 9 } });
    expect(acc.content).toBe('hello');
    expect(acc.toolCalls.get(0)?.name).toBe('read');
    expect(acc.finishReason).toBe('tool_calls');
    expect((acc.usage as { prompt_tokens: number }).prompt_tokens).toBe(9);
  });
});
