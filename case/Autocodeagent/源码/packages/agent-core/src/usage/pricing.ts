/**
 * 模型计价表（P6 任务 3）：美元 / 1M tokens。
 * 精确匹配优先，其次子串匹配（如 gpt-4o-mini-2024-07-18 命中 gpt-4o-mini）；
 * 未知模型单价 0（费用显示 $0.00 而非报错）。
 * 缓存输入按 cacheInput 计价（未单列的厂商与输入同价）。
 */
import type { NormalizedUsage } from '@agentbuddy/shared';

export interface ModelPrice {
  /** 输入 $/1M */
  input: number;
  /** 输出 $/1M */
  output: number;
  /** 缓存命中输入 $/1M */
  cacheInput: number;
}

export const MODEL_PRICING: Record<string, ModelPrice> = {
  'gpt-5-mini': { input: 0.25, output: 2.5, cacheInput: 0.025 },
  'gpt-4o-mini': { input: 0.15, output: 0.6, cacheInput: 0.075 },
  'deepseek-chat': { input: 0.27, output: 1.1, cacheInput: 0.07 },
  'deepseek-reasoner': { input: 0.55, output: 2.19, cacheInput: 0.14 },
  'qwen-plus': { input: 0.4, output: 1.2, cacheInput: 0.4 },
  'glm-4-plus': { input: 1.43, output: 1.43, cacheInput: 1.43 },
};

const ZERO: ModelPrice = { input: 0, output: 0, cacheInput: 0 };

/** 查单价：精确 → 子串 → 0 */
export function priceOf(model: string): ModelPrice {
  const exact = MODEL_PRICING[model];
  if (exact) return exact;
  for (const [key, price] of Object.entries(MODEL_PRICING)) {
    if (model.includes(key)) return price;
  }
  return ZERO;
}

/**
 * 单请求估算费用（美元）：
 * (输入 − 缓存命中) × 输入价 + 缓存命中 × 缓存价 + 输出 × 输出价，均按 1M 折算。
 */
export function costOf(model: string, usage: NormalizedUsage): number {
  const p = priceOf(model);
  const cached = Math.min(usage.cacheReadTokens, usage.promptTokens);
  const billedInput = Math.max(0, usage.promptTokens - cached);
  return (billedInput * p.input + cached * p.cacheInput + usage.completionTokens * p.output) / 1_000_000;
}
