/**
 * usage 跨厂商归一（技术方案 §4.7）：
 * OpenAI: usage.prompt_tokens_details.cached_tokens
 * DeepSeek: usage.prompt_cache_hit_tokens
 * Anthropic(兼容层): usage.cache_read_input_tokens
 */
import type { NormalizedUsage } from '@agentbuddy/shared';

interface RawUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  prompt_tokens_details?: { cached_tokens?: number };
  prompt_cache_hit_tokens?: number;
  cache_read_input_tokens?: number;
}

const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : 0);

export function normalizeUsage(raw: unknown): NormalizedUsage {
  const u = (raw ?? {}) as RawUsage;
  const cacheReadTokens = Math.max(
    num(u.prompt_tokens_details?.cached_tokens),
    num(u.prompt_cache_hit_tokens),
    num(u.cache_read_input_tokens),
  );
  const promptTokens = num(u.prompt_tokens);
  const completionTokens = num(u.completion_tokens);
  return {
    promptTokens,
    completionTokens,
    totalTokens: num(u.total_tokens) || promptTokens + completionTokens,
    cacheReadTokens,
  };
}
