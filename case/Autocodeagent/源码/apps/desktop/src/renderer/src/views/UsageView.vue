<script setup lang="ts">
/**
 * P6 任务 6：用量统计页 —— 三 Tab（总览 / 模型消耗 / 执行记录）。
 * 数据全部来自本机 usage.jsonl / records.jsonl 聚合，不上送云端；
 * 执行记录支持 会话 × 工具 组合筛选（Main 侧过滤，空结果有占位）。
 */
import { computed, onMounted, ref, watch } from 'vue';
import type { SessionMeta, ToolRecord, UsageStats } from '@agentbuddy/shared';
import { agent } from '../api/bridge';
import { ico } from '../ui/icons';

type Tab = 'overview' | 'models' | 'records';

const tab = ref<Tab>('overview');
const stats = ref<UsageStats | null>(null);
const records = ref<ToolRecord[]>([]);
const sessions = ref<SessionMeta[]>([]);
const filterSession = ref('all');
const filterTool = ref('all');

const RISK_CLASS: Record<string, string> = {
  READ: 'text-stone-600 bg-stone-500/10',
  WRITE: 'text-amber-700 bg-amber-500/10',
  EXEC: 'text-blue-700 bg-blue-500/10',
  NETWORK: 'text-purple-700 bg-purple-500/10',
  DANGEROUS: 'text-rose-700 bg-rose-500/10',
};

function riskClass(risk: string): string {
  return RISK_CLASS[risk] ?? RISK_CLASS['READ']!;
}

/** 模型占比（总 Token 为 0 时返回 0，避免除零） */
function shareOf(input: number, output: number): number {
  const total = stats.value?.totals.tokens ?? 0;
  return total > 0 ? Math.round(((input + output) / total) * 100) : 0;
}

/** 单模型缓存命中率（无输入时 0%，不报错） */
function hitRateOf(input: number, cacheRead: number): number {
  return input > 0 ? Math.round((cacheRead / input) * 100) : 0;
}

function fmtK(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtTime(ts: number): string {
  const d = new Date(ts);
  const p = (x: number) => String(x).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function fmtMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function sessionTitle(id: string): string {
  return sessions.value.find((s) => s.id === id)?.title ?? id.slice(0, 8);
}

const maxDaily = computed(() => Math.max(1, ...(stats.value?.daily ?? []).map((d) => d.tokens)));
/** 工具下拉选项取全量分布（不受记录筛选影响） */
const toolOptions = computed(() => (stats.value?.byTool ?? []).map((t) => t.tool));

async function loadStats(): Promise<void> {
  const res = await agent().usage.stats();
  if (res.ok && res.data) stats.value = res.data;
}

async function loadRecords(): Promise<void> {
  const res = await agent().usage.records({
    sessionId: filterSession.value === 'all' ? undefined : filterSession.value,
    tool: filterTool.value === 'all' ? undefined : filterTool.value,
  });
  if (res.ok && res.data) records.value = res.data;
}

watch([filterSession, filterTool], () => void loadRecords());

onMounted(async () => {
  const list = await agent().session.list();
  if (list.ok && list.data) sessions.value = list.data;
  await Promise.all([loadStats(), loadRecords()]);
});
</script>

<template>
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- 页头 + Tab 切换 -->
    <div class="h-12 border-b border-border bg-surface/50 px-4 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <span class="text-accent" v-html="ico('chart')" />
        <div>
          <h2 class="font-bold text-stone-900 text-sm">用量统计</h2>
          <p class="text-[10px] text-stone-500">本机会话消耗与工具调用回放 · 不上送云端</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button
          v-for="t in (['overview', 'models', 'records'] as Tab[])"
          :key="t"
          :class="['px-3.5 py-1.5 rounded-full text-xs font-medium transition-std', tab === t ? 'tab-active' : 'text-stone-600 hover:bg-card']"
          @click="tab = t"
        >{{ t === 'overview' ? '总览' : t === 'models' ? '模型消耗' : '执行记录' }}</button>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto p-6 space-y-4">
      <!-- 总览：五卡 + 7 日柱状图 + 工具分布 -->
      <div v-if="tab === 'overview' && stats" class="space-y-4">
        <div class="grid grid-cols-2 xl:grid-cols-5 gap-4">
          <div class="bg-card border border-border rounded-xl p-4 shadow-card">
            <div class="text-[10px] text-stone-500">总 Token 消耗</div>
            <div class="text-xl font-bold font-mono text-stone-900 mt-1">{{ fmtK(stats.totals.tokens) }}</div>
            <div class="text-[9px] text-stone-400 mt-0.5">输入 {{ fmtK(stats.totals.promptTokens) }} + 输出 {{ fmtK(stats.totals.completionTokens) }}</div>
          </div>
          <div class="bg-card border border-border rounded-xl p-4 shadow-card">
            <div class="text-[10px] text-stone-500">估算费用</div>
            <div class="text-xl font-bold font-mono text-accent mt-1">$ {{ stats.totals.cost.toFixed(4) }}</div>
            <div class="text-[9px] text-stone-400 mt-0.5">按各模型计价累加</div>
          </div>
          <div class="bg-card border border-border rounded-xl p-4 shadow-card">
            <div class="text-[10px] text-stone-500">工具调用</div>
            <div class="text-xl font-bold font-mono text-stone-900 mt-1">{{ stats.totals.calls }}</div>
            <div class="text-[9px] text-stone-400 mt-0.5">内置 + MCP</div>
          </div>
          <div class="bg-card border border-border rounded-xl p-4 shadow-card">
            <div class="text-[10px] text-stone-500">会话数</div>
            <div class="text-xl font-bold font-mono text-stone-900 mt-1">{{ stats.totals.sessions }}</div>
            <div class="text-[9px] text-stone-400 mt-0.5">全部代码空间</div>
          </div>
          <div class="bg-card border border-border rounded-xl p-4 shadow-card">
            <div class="text-[10px] text-stone-500">缓存命中率</div>
            <div class="text-xl font-bold font-mono text-emerald-700 mt-1">{{ stats.totals.cacheHitRate }}%</div>
            <div class="text-[9px] text-stone-400 mt-0.5">Prompt Cache · 命中 {{ fmtK(stats.totals.cacheReadTokens) }} tokens</div>
          </div>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <!-- 近 7 日 Token 柱状图 -->
          <div class="bg-card border border-border rounded-xl p-4 shadow-card">
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-[12px] font-semibold text-stone-900">近 7 日 Token 用量</h3>
              <span class="text-[10px] text-stone-500 font-mono">合计 {{ fmtK(stats.daily.reduce((s, d) => s + d.tokens, 0)) }}</span>
            </div>
            <div class="flex items-end gap-2 h-28">
              <div
                v-for="d in stats.daily"
                :key="d.day"
                class="flex-1 h-full flex flex-col justify-end items-center gap-1"
                :title="`${d.day} · ${d.tokens} tokens`"
              >
                <div class="w-full rounded-t-md bg-accent/60 hover:bg-accent transition-std" :style="{ height: Math.max(6, (d.tokens / maxDaily) * 100) + '%' }" />
                <span class="text-[9px] text-stone-400 font-mono">{{ d.day.slice(3) }}</span>
              </div>
            </div>
          </div>
          <!-- 工具调用分布 -->
          <div class="bg-card border border-border rounded-xl p-4 shadow-card">
            <h3 class="text-[12px] font-semibold text-stone-900 mb-3">工具调用分布</h3>
            <div class="space-y-2.5">
              <div v-for="t in stats.byTool" :key="t.tool" class="flex items-center gap-2">
                <span class="w-28 truncate font-mono text-[10px] text-stone-600" :title="t.tool">{{ t.tool }}</span>
                <div class="flex-1 h-2 bg-surface rounded-full overflow-hidden">
                  <div class="h-full bg-indigo-500/60 rounded-full" :style="{ width: (t.count / (stats.byTool[0]?.count ?? 1)) * 100 + '%' }" />
                </div>
                <span class="w-8 text-right font-mono text-[10px] text-stone-500">{{ t.count }}</span>
              </div>
              <div v-if="!stats.byTool.length" class="text-[11px] text-stone-400 py-2 text-center">暂无工具调用记录</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 模型消耗 -->
      <div v-else-if="tab === 'models' && stats" class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div v-for="m in stats.byModel" :key="m.model" class="bg-card border border-border rounded-xl p-4 shadow-card">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-semibold text-stone-800 truncate font-mono text-[12px]" :title="m.model">{{ m.model }}</h3>
            <span class="text-[9px] px-1.5 py-0.5 rounded-full font-mono bg-stone-100 text-stone-600 border border-stone-300 shrink-0">{{ m.provider }}</span>
          </div>
          <div class="grid grid-cols-2 gap-1.5 text-[10px] mb-3">
            <div class="flex justify-between bg-surface rounded-md px-2 py-1"><span class="text-stone-400">请求</span><span class="text-stone-700 font-mono">{{ m.reqs }}</span></div>
            <div class="flex justify-between bg-surface rounded-md px-2 py-1"><span class="text-stone-400">费用</span><span class="text-accent font-mono">$ {{ m.cost.toFixed(4) }}</span></div>
            <div class="flex justify-between bg-surface rounded-md px-2 py-1"><span class="text-stone-400">输入</span><span class="text-stone-700 font-mono">{{ fmtK(m.input) }}</span></div>
            <div class="flex justify-between bg-surface rounded-md px-2 py-1"><span class="text-stone-400">输出</span><span class="text-stone-700 font-mono">{{ fmtK(m.output) }}</span></div>
            <div class="flex justify-between bg-surface rounded-md px-2 py-1"><span class="text-stone-400">缓存命中</span><span class="text-stone-700 font-mono">{{ fmtK(m.cacheRead) }}</span></div>
            <div class="flex justify-between bg-surface rounded-md px-2 py-1"><span class="text-stone-400">命中率</span><span class="text-emerald-700 font-mono">{{ hitRateOf(m.input, m.cacheRead) }}%</span></div>
          </div>
          <div class="text-[9px] text-stone-400 mb-1">占总 Token {{ shareOf(m.input, m.output) }}%</div>
          <div class="h-2 bg-surface rounded-full overflow-hidden">
            <div class="h-full bg-accent/70 rounded-full" :style="{ width: shareOf(m.input, m.output) + '%' }" />
          </div>
        </div>
        <div v-if="!stats.byModel.length" class="col-span-full text-[11px] text-stone-400 py-8 text-center">暂无模型用量记录</div>
      </div>

      <!-- 执行记录 -->
      <div v-else-if="tab === 'records'" class="space-y-3">
        <div class="flex items-center justify-between">
          <div>
            <h3 class="text-sm font-bold text-stone-900">执行记录</h3>
            <p class="text-[10px] text-stone-500 mt-0.5">本机所有工具调用的回放视图（非上送审计），可按会话 / 工具筛选</p>
          </div>
          <div class="flex items-center gap-2">
            <select v-model="filterSession" class="bg-surface border border-border rounded-lg px-2.5 py-1.5 text-[11px] outline-none text-stone-700 transition-std max-w-[180px]">
              <option value="all">全部会话</option>
              <option v-for="s in sessions" :key="s.id" :value="s.id">{{ s.title }}</option>
            </select>
            <select v-model="filterTool" class="bg-surface border border-border rounded-lg px-2.5 py-1.5 text-[11px] outline-none text-stone-700 transition-std">
              <option value="all">全部工具</option>
              <option v-for="t in toolOptions" :key="t" :value="t">{{ t }}</option>
            </select>
          </div>
        </div>

        <div class="bg-card border border-border rounded-xl overflow-hidden shadow-card">
          <table class="w-full text-[11px]">
            <thead>
              <tr class="text-left text-stone-500 border-b border-border bg-surface">
                <th class="px-3 py-2.5 font-medium">时间</th>
                <th class="px-3 py-2.5 font-medium">会话</th>
                <th class="px-3 py-2.5 font-medium">工具</th>
                <th class="px-3 py-2.5 font-medium">对象</th>
                <th class="px-3 py-2.5 font-medium">风险</th>
                <th class="px-3 py-2.5 font-medium">结果</th>
                <th class="px-3 py-2.5 font-medium">耗时</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in records" :key="`${r.ts}-${i}`" class="border-b border-border/60 hover:bg-cardHover/60 transition-std">
                <td class="px-3 py-2 font-mono text-stone-500 whitespace-nowrap">{{ fmtTime(r.ts) }}</td>
                <td class="px-3 py-2 text-stone-700 max-w-[140px] truncate" :title="sessionTitle(r.sessionId)">{{ sessionTitle(r.sessionId) }}</td>
                <td class="px-3 py-2 font-mono text-indigo-700">{{ r.tool }}</td>
                <td class="px-3 py-2 font-mono text-stone-600 truncate max-w-[180px]" :title="r.target">{{ r.target || '—' }}</td>
                <td class="px-3 py-2">
                  <span :class="['text-[9px] px-1.5 py-0.5 rounded-full font-mono', riskClass(r.risk)]">{{ r.risk }}</span>
                </td>
                <td class="px-3 py-2" :class="r.ok ? 'text-emerald-700' : 'text-rose-600'">{{ r.ok ? '成功' : '失败' }}</td>
                <td class="px-3 py-2 font-mono text-stone-500">{{ fmtMs(r.ms) }}</td>
              </tr>
              <tr v-if="!records.length">
                <td colspan="7" class="px-3 py-6 text-center text-stone-400">无匹配的执行记录</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
