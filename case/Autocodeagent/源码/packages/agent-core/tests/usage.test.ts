import { describe, expect, it } from 'vitest';
import { normalizeUsage } from '../src/llm/usage';
import { maskKey } from '@agentbuddy/shared';

describe('normalizeUsage 跨厂商归一', () => {
  it('OpenAI: prompt_tokens_details.cached_tokens', () => {
    const u = normalizeUsage({ prompt_tokens: 100, completion_tokens: 20, prompt_tokens_details: { cached_tokens: 60 } });
    expect(u).toEqual({ promptTokens: 100, completionTokens: 20, totalTokens: 120, cacheReadTokens: 60 });
  });

  it('DeepSeek: prompt_cache_hit_tokens', () => {
    const u = normalizeUsage({ prompt_tokens: 80, prompt_cache_hit_tokens: 40 });
    expect(u.cacheReadTokens).toBe(40);
    expect(u.totalTokens).toBe(80); // 无 total 时回退求和
  });

  it('Anthropic(兼容层): cache_read_input_tokens', () => {
    const u = normalizeUsage({ prompt_tokens: 50, cache_read_input_tokens: 25, total_tokens: 75 });
    expect(u.cacheReadTokens).toBe(25);
    expect(u.totalTokens).toBe(75);
  });

  it('缺失/非法输入全部归 0，不抛错', () => {
    expect(normalizeUsage(null)).toEqual({ promptTokens: 0, completionTokens: 0, totalTokens: 0, cacheReadTokens: 0 });
    expect(normalizeUsage({ prompt_tokens: -5 }).promptTokens).toBe(0);
  });
});

describe('maskKey', () => {
  it('保留尾 4 位', () => {
    expect(maskKey('sk-abc123xyz')).toBe('****3xyz');
  });
  it('短 key 全掩', () => {
    expect(maskKey('abc')).toBe('****');
  });
});
