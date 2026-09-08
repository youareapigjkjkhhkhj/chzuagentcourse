/** P6 任务 3/4/5：UsageStore 追加与聚合单测
 * 验收：缓存命中率不支持=0% 不报错；筛选组合正确 + 空占位；≥1 万行聚合 <200ms */
import { appendFile, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { UsageStore } from '../src/usage/store';

let dir: string;
let store: UsageStore;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), 'usage-'));
  store = new UsageStore(dir);
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

describe('stats 聚合', () => {
  it('空目录返回零值视图：缓存命中率 0% 而非报错', async () => {
    const s = await store.stats();
    expect(s.totals).toEqual({
      tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0,
      calls: 0, sessions: 0, cacheHitRate: 0, cacheReadTokens: 0,
    });
    expect(s.daily).toHaveLength(7);
    expect(s.daily.every((d) => d.tokens === 0)).toBe(true);
    expect(s.byTool).toEqual([]);
    expect(s.byModel).toEqual([]);
  });

  it('总量 / 按模型 / 费用累加正确', async () => {
    await store.recordUsage({ sessionId: 's1', model: 'gpt-5-mini', provider: 'openai', promptTokens: 1000, completionTokens: 500, totalTokens: 1500, cacheReadTokens: 200 });
    await store.recordUsage({ sessionId: 's2', model: 'deepseek-chat', provider: 'deepseek', promptTokens: 100, completionTokens: 100, totalTokens: 200, cacheReadTokens: 0 });
    const s = await store.stats();
    expect(s.totals.tokens).toBe(1700);
    expect(s.totals.sessions).toBe(2);
    // 手工核算：0.001455 + (100×0.27 + 100×1.1)/1e6 = 0.001455 + 0.000137
    expect(s.totals.cost).toBeCloseTo(0.001455 + 0.000137, 10);
    // 缓存命中率 = round(200/1100×100) = 18
    expect(s.totals.cacheHitRate).toBe(18);
    expect(s.byModel.map((m) => m.model)).toEqual(['gpt-5-mini', 'deepseek-chat']);
    expect(s.byModel[0]?.reqs).toBe(1);
    expect(s.daily.at(-1)?.tokens).toBe(1700); // 今天计入最后一柱
  });

  it('days 范围过滤：旧记录被排除', async () => {
    const tenDaysAgo = Date.now() - 10 * 86_400_000;
    await store.recordUsage({ ts: tenDaysAgo, sessionId: 'old', model: 'gpt-5-mini', provider: 'openai', promptTokens: 500, completionTokens: 500, totalTokens: 1000, cacheReadTokens: 0 });
    await store.recordUsage({ sessionId: 'new', model: 'gpt-5-mini', provider: 'openai', promptTokens: 100, completionTokens: 0, totalTokens: 100, cacheReadTokens: 0 });
    const week = await store.stats(7);
    expect(week.totals.tokens).toBe(100);
    const all = await store.stats();
    expect(all.totals.tokens).toBe(1100);
  });

  it('畸形行跳过，不击穿统计', async () => {
    await store.recordUsage({ sessionId: 's1', model: 'gpt-5-mini', provider: 'openai', promptTokens: 10, completionTokens: 10, totalTokens: 20, cacheReadTokens: 0 });
    await appendFile(join(dir, 'usage.jsonl'), '{bad json\n\n', 'utf-8');
    const s = await store.stats();
    expect(s.totals.tokens).toBe(20);
  });
});

describe('records 执行记录', () => {
  it('会话 × 工具组合筛选正确；倒序；空结果返回空数组', async () => {
    await store.recordTool({ sessionId: 's1', tool: 'read', target: 'a.txt', risk: 'READ', ok: true, ms: 5 });
    await store.recordTool({ sessionId: 's1', tool: 'bash', target: 'ls', risk: 'EXEC', ok: false, ms: 12 });
    await store.recordTool({ sessionId: 's2', tool: 'read', target: 'b.txt', risk: 'READ', ok: true, ms: 3 });
    expect((await store.records()).length).toBe(3);
    expect((await store.records({ sessionId: 's1' })).map((r) => r.tool)).toEqual(['bash', 'read']); // 倒序
    expect((await store.records({ sessionId: 's1', tool: 'read' })).length).toBe(1);
    expect(await store.records({ sessionId: 'nobody', tool: 'read' })).toEqual([]); // 空占位数据源
    expect((await store.records({ tool: 'bash' })).length).toBe(1);
  });

  it('stats.byTool 按调用次数降序', async () => {
    await store.recordTool({ sessionId: 's1', tool: 'grep', target: 'x', risk: 'READ', ok: true, ms: 1 });
    await store.recordTool({ sessionId: 's1', tool: 'grep', target: 'y', risk: 'READ', ok: true, ms: 1 });
    await store.recordTool({ sessionId: 's1', tool: 'edit', target: 'z', risk: 'WRITE', ok: true, ms: 1 });
    const s = await store.stats();
    expect(s.byTool).toEqual([
      { tool: 'grep', count: 2 },
      { tool: 'edit', count: 1 },
    ]);
    expect(s.totals.calls).toBe(3);
  });
});

describe('性能：万行级聚合', () => {
  it('1 万行 usage + records 聚合 < 200ms', async () => {
    const now = Date.now();
    let usageLines = '';
    for (let i = 0; i < 10_000; i++) {
      usageLines += `${JSON.stringify({ ts: now - (i % 7) * 3_600_000, sessionId: `s${i % 5}`, model: 'gpt-5-mini', provider: 'openai', promptTokens: 100, completionTokens: 50, totalTokens: 150, cacheReadTokens: 20 })}\n`;
    }
    let recordLines = '';
    for (let i = 0; i < 10_000; i++) {
      recordLines += `${JSON.stringify({ ts: now - (i % 7) * 3_600_000, sessionId: `s${i % 5}`, tool: i % 2 ? 'grep' : 'read', target: 'f.txt', risk: 'READ', ok: true, ms: 2 })}\n`;
    }
    await writeFile(join(dir, 'usage.jsonl'), usageLines, 'utf-8');
    await writeFile(join(dir, 'records.jsonl'), recordLines, 'utf-8');

    const t0 = performance.now();
    const s = await store.stats(7);
    const records = await store.records({ sessionId: 's1' });
    const elapsed = performance.now() - t0;

    expect(s.totals.tokens).toBe(10_000 * 150);
    expect(records.length).toBe(2000); // 上限截断
    expect(elapsed).toBeLessThan(200);
  }, 30_000);
});
