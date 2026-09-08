/**
 * 用量 / 执行记录存储（P6 任务 3 / 4 / 5）：
 * `~/.AgentBuddy/usage.jsonl` 与 `records.jsonl` 追加写；
 * stats({days}) / records({sessionId, tool}) 读 JSONL 内存聚合（1 万行级 <200ms）。
 * 畸形行跳过不击穿；空数据返回零值视图（缓存命中率 0% 而非报错）。
 */
import { appendFile, mkdir, readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import type { ToolRecord, UsageEntry, UsageStats } from '@agentbuddy/shared';
import { costOf } from './pricing';

export class UsageStore {
  constructor(private readonly dataDir: string) {}

  private get usageFile(): string {
    return join(this.dataDir, 'usage.jsonl');
  }

  private get recordsFile(): string {
    return join(this.dataDir, 'records.jsonl');
  }

  /* ── 追加（每次 LLM 响应 / 工具调用一行） ── */

  async recordUsage(entry: Omit<UsageEntry, 'ts'> & { ts?: number }): Promise<void> {
    await this.append(this.usageFile, { ts: Date.now(), ...entry });
  }

  async recordTool(entry: Omit<ToolRecord, 'ts'> & { ts?: number }): Promise<void> {
    await this.append(this.recordsFile, { ts: Date.now(), ...entry });
  }

  private async append(file: string, line: unknown): Promise<void> {
    await mkdir(dirname(file), { recursive: true });
    await appendFile(file, `${JSON.stringify(line)}\n`, 'utf-8');
  }

  /* ── 聚合 ── */

  /** range：days = 近 N 天（含今天）；缺省全量 */
  async stats(days?: number): Promise<UsageStats> {
    const from = days !== undefined ? startOfDaysAgo(days) : undefined;
    const usage = (await this.readJsonl<UsageEntry>(this.usageFile)).filter((e) => from === undefined || e.ts >= from);
    const records = (await this.readJsonl<ToolRecord>(this.recordsFile)).filter((r) => from === undefined || r.ts >= from);

    let prompt = 0;
    let completion = 0;
    let cacheRead = 0;
    let cost = 0;
    const modelAgg = new Map<string, { model: string; provider: string; reqs: number; input: number; output: number; cacheRead: number; cost: number }>();
    for (const e of usage) {
      prompt += e.promptTokens;
      completion += e.completionTokens;
      cacheRead += e.cacheReadTokens;
      const c = costOf(e.model, e);
      cost += c;
      const m = modelAgg.get(e.model) ?? { model: e.model, provider: e.provider, reqs: 0, input: 0, output: 0, cacheRead: 0, cost: 0 };
      m.reqs += 1;
      m.input += e.promptTokens;
      m.output += e.completionTokens;
      m.cacheRead += e.cacheReadTokens;
      m.cost += c;
      modelAgg.set(e.model, m);
    }

    const toolAgg = new Map<string, number>();
    const sessionIds = new Set<string>();
    for (const r of records) {
      toolAgg.set(r.tool, (toolAgg.get(r.tool) ?? 0) + 1);
      sessionIds.add(r.sessionId);
    }
    for (const e of usage) sessionIds.add(e.sessionId);

    return {
      totals: {
        tokens: prompt + completion,
        promptTokens: prompt,
        completionTokens: completion,
        cost,
        calls: records.length,
        sessions: sessionIds.size,
        cacheHitRate: prompt > 0 ? Math.round((cacheRead / prompt) * 100) : 0,
        cacheReadTokens: cacheRead,
      },
      daily: this.daily(usage),
      byTool: [...toolAgg.entries()].map(([tool, count]) => ({ tool, count })).sort((a, b) => b.count - a.count),
      byModel: [...modelAgg.values()].sort((a, b) => b.input + b.output - (a.input + a.output)),
    };
  }

  /** 执行记录：会话 × 工具组合筛选，倒序，上限 2000 行（UI 回放视图） */
  async records(filter?: { sessionId?: string; tool?: string }): Promise<ToolRecord[]> {
    const all = await this.readJsonl<ToolRecord>(this.recordsFile);
    const filtered = all.filter(
      (r) =>
        (filter?.sessionId === undefined || r.sessionId === filter.sessionId) &&
        (filter?.tool === undefined || r.tool === filter.tool),
    );
    return filtered.sort((a, b) => b.ts - a.ts).slice(0, 2000);
  }

  /** 近 7 日（含今天）Token 柱状图数据，缺日补 0 */
  private daily(usage: UsageEntry[]): Array<{ day: string; tokens: number }> {
    const byDay = new Map<string, number>();
    for (const e of usage) {
      const key = dayKey(e.ts);
      byDay.set(key, (byDay.get(key) ?? 0) + e.promptTokens + e.completionTokens);
    }
    const out: Array<{ day: string; tokens: number }> = [];
    for (let i = 6; i >= 0; i--) {
      const key = dayKey(Date.now() - i * 86_400_000);
      out.push({ day: key, tokens: byDay.get(key) ?? 0 });
    }
    return out;
  }

  private async readJsonl<T>(file: string): Promise<T[]> {
    const raw = await readFile(file, 'utf-8').catch(() => null);
    if (raw === null) return [];
    const out: T[] = [];
    for (const line of raw.split('\n')) {
      const t = line.trim();
      if (!t) continue;
      try {
        out.push(JSON.parse(t) as T);
      } catch {
        /* 畸形行跳过，不击穿统计 */
      }
    }
    return out;
  }
}

function dayKey(ts: number): string {
  const d = new Date(ts);
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** 近 N 天起点（含今天）：今天 0 点 − (N−1) 天 */
function startOfDaysAgo(days: number): number {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.getTime() - (days - 1) * 86_400_000;
}
