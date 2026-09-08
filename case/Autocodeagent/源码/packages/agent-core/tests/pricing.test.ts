/** P6 任务 3：计价表与费用核算单测（验收：估算费用与手工核算一致；未知模型 0 不报错） */
import { describe, expect, it } from 'vitest';
import { costOf, MODEL_PRICING, priceOf } from '../src/usage/pricing';

describe('priceOf 单价查询', () => {
  it('精确匹配命中计价表', () => {
    expect(priceOf('gpt-5-mini')).toEqual({ input: 0.25, output: 2.5, cacheInput: 0.025 });
  });

  it('带日期版本号走子串匹配', () => {
    expect(priceOf('gpt-4o-mini-2024-07-18').output).toBe(0.6);
    expect(priceOf('deepseek-chat-latest').cacheInput).toBe(0.07);
  });

  it('未知模型单价全 0（不抛错）', () => {
    expect(priceOf('my-custom-model')).toEqual({ input: 0, output: 0, cacheInput: 0 });
  });

  it('计价表覆盖三厂商代表模型', () => {
    for (const m of ['gpt-4o-mini', 'deepseek-chat', 'qwen-plus', 'glm-4-plus']) {
      expect(MODEL_PRICING[m]).toBeDefined();
    }
  });
});

describe('costOf 费用核算', () => {
  it('与手工核算一致：非缓存输入 + 缓存价 + 输出价', () => {
    // gpt-5-mini：(800×0.25 + 200×0.025 + 500×2.5) / 1e6 = 0.001455
    const c = costOf('gpt-5-mini', { promptTokens: 1000, completionTokens: 500, totalTokens: 1500, cacheReadTokens: 200 });
    expect(c).toBeCloseTo(0.001455, 10);
  });

  it('cacheRead 超过 prompt 时按 prompt 封顶（不产生负费用）', () => {
    const c = costOf('deepseek-chat', { promptTokens: 10, completionTokens: 0, totalTokens: 10, cacheReadTokens: 1000 });
    expect(c).toBeCloseTo((10 * 0.07) / 1_000_000, 12);
  });

  it('无缓存字段 = 纯输入输出计价', () => {
    const c = costOf('glm-4-plus', { promptTokens: 1_000_000, completionTokens: 1_000_000, totalTokens: 2_000_000, cacheReadTokens: 0 });
    expect(c).toBeCloseTo(2.86, 6);
  });

  it('未知模型费用为 0', () => {
    expect(costOf('whatever-model', { promptTokens: 100, completionTokens: 100, totalTokens: 200, cacheReadTokens: 0 })).toBe(0);
  });
});
