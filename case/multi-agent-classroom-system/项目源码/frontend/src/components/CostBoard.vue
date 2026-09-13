<script setup lang="ts">
/**
 * 成本看板（P5-F5-7 / §4.2）—— 设置页「成本」那一档的上半截。
 *
 * 三件事只说一遍，别处（时间线、预算）都是同一份口径：
 *
 * 1. **金额是估算**。它是本机价目表乘出来的，与上游账单不会逐分对上。
 *    响应里带着的那句 `note` 每次都照原样渲染出来 —— 一旦界面上出现「费用」，
 *    就会有人拿它去对账。
 * 2. **四条链路一条都不少**。没量的那条给一行 0：图例的条数不该随这个月
 *    的用量变。
 * 3. **未配单价的链路会让合计少报**（`priced === false`）。这时要明说，
 *    而不是让一个偏小的数看起来像全部。
 *
 * 分组那三个口径对应人的三个问题：哪天花得多 / 哪门课贵 / 哪条链路贵。
 * 「按链路」这一档直接读 `byKind` —— 服务端给的 `items` 在那时就是这份平铺
 * 数据（同一个函数出的），绕一层壳没有意义。
 */
import { computed, onMounted, ref, watch } from 'vue'

import * as api from '@/api'
import type { UsageBucket, UsageGroup, UsageGroupBy, UsageSummary } from '@/types/api'
import { USAGE_KIND_LABELS } from '@/utils/labels'
import { formatCost, formatUnits } from '@/utils/voice'

const RANGES = [
  { key: '30', label: '最近 30 天', days: 30 },
  { key: '7', label: '最近 7 天', days: 7 },
  { key: 'today', label: '今天', days: 1 },
] as const

const GROUPS: { key: UsageGroupBy; label: string }[] = [
  { key: 'day', label: '按天' },
  { key: 'course', label: '按课程' },
  { key: 'kind', label: '按链路' },
]

type RangeKey = (typeof RANGES)[number]['key']

const range = ref<RangeKey>('30')
const groupBy = ref<UsageGroupBy>('day')
const data = ref<UsageSummary | null>(null)
const loading = ref(false)
const error = ref('')

/**
 * 本地日。看板的日界就是本地日（后端 `USAGE_DAY_OFFSET_HOURS` 缺省东八区，
 * 与浏览器同处一地），所以「今天」由这里算，不用 UTC 那一套 —— 用 UTC 的话
 * 北京时间早上 8 点之前看到的都是昨天。
 */
function dayString(offsetDays = 0): string {
  const date = new Date()
  date.setDate(date.getDate() + offsetDays)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

async function load(): Promise<void> {
  const days = RANGES.find((item) => item.key === range.value)?.days ?? 30
  loading.value = true
  try {
    data.value = await api.fetchUsageSummary({
      from: dayString(-(days - 1)),
      to: dayString(),
      groupBy: groupBy.value,
    })
    error.value = ''
  } catch {
    // 看板是打开就能看的一屏：读不出来时说清是读取失败，而不是画一堆 0
    //（一堆 0 会被当成「这个月没花钱」）。
    data.value = null
    error.value = '用量读取失败，稍后再试'
  } finally {
    loading.value = false
  }
}

watch([range, groupBy], () => void load())
onMounted(load)

/** 分组表里的行。按链路那一档服务端给的是平铺的四条链路（见模块 docstring）。 */
const groups = computed<UsageGroup[]>(() => {
  const current = data.value
  if (!current || current.groupBy === 'kind') return []
  return current.items.filter((item): item is UsageGroup => 'kinds' in item)
})

/** 按链路这一档读 `byKind`：与服务端 `items` 同一份数据，少一层壳。 */
const flatKinds = computed<UsageBucket[]>(() => data.value?.byKind ?? [])

/** 一条链路在这一行里的量：LLM 说 token，语音说字符/秒。 */
function bucketText(bucket: UsageBucket): string {
  const bits: string[] = []
  if (bucket.totalTokens) bits.push(`${bucket.totalTokens} tokens`)
  if (bucket.totalUnits && bucket.unitName) bits.push(formatUnits(bucket.unitName, bucket.totalUnits))
  if (!bits.length) return bucket.calls ? `${bucket.calls} 次调用` : ''
  if (bucket.calls) bits.push(`${bucket.calls} 次`)
  return bits.join(' · ')
}

/** 分组行里的链路摘要（「大模型 ¥1.20 · 语音合成 ¥0.03」）。 */
function kindsText(kinds: UsageBucket[]): string {
  return kinds
    .filter((kind) => kind.estCost || kind.totalTokens || kind.totalUnits)
    .map((kind) => `${USAGE_KIND_LABELS[kind.kind] ?? kind.kind} ${formatCost(kind.estCost)}`)
    .join(' · ')
}

function kindLabel(kind: string): string {
  return USAGE_KIND_LABELS[kind as keyof typeof USAGE_KIND_LABELS] ?? kind
}
</script>

<template>
  <section class="panel">
    <h3 class="panel__title">用量与成本</h3>
    <p class="panel__desc">
      每一次大模型调用与每一次语音合成都会记一笔。金额按本机价目表估算，
      <strong>以服务商账单为准</strong>。
    </p>

    <div class="cb-filters">
      <t-radio-group v-model="range" variant="default-filled" size="small">
        <t-radio-button v-for="item in RANGES" :key="item.key" :value="item.key">
          {{ item.label }}
        </t-radio-button>
      </t-radio-group>
      <t-radio-group v-model="groupBy" variant="outline" size="small">
        <t-radio-button v-for="item in GROUPS" :key="item.key" :value="item.key">
          {{ item.label }}
        </t-radio-button>
      </t-radio-group>
    </div>

    <p v-if="loading && !data" class="cb-hint">读取中…</p>
    <p v-else-if="error" class="cb-hint is-error">{{ error }}</p>

    <template v-else-if="data">
      <!-- 四条链路一条都不少：每张卡一个数，左边是钱，右边是量 -->
      <div class="cb-kinds">
        <div v-for="bucket in flatKinds" :key="bucket.kind" class="cb-kind">
          <span class="cb-kind__name">{{ kindLabel(bucket.kind) }}</span>
          <span class="cb-kind__cost mono">{{ formatCost(bucket.estCost) }}</span>
          <span class="cb-kind__meta">{{ bucketText(bucket) || '本期没有用量' }}</span>
        </div>
      </div>

      <div class="cb-total">
        <span>合计</span>
        <span class="mono">{{ formatCost(data.totals.estCost) }}</span>
        <span class="cb-total__meta">
          {{ data.totals.calls }} 次调用 · {{ data.totals.totalTokens }} tokens
          <template v-if="data.totals.totalUnits"> · {{ data.totals.totalUnits }} 单位</template>
        </span>
      </div>

      <p v-if="!data.priced" class="cb-warn">
        有链路还没配单价，上面的合计是<strong>少报</strong>的 —— 去下面的价目表补一下。
      </p>

      <div class="cb-table">
        <div class="cb-table__head">
          <span>{{
            data.groupBy === 'kind' ? '链路' : data.groupBy === 'course' ? '课程' : '日期'
          }}</span>
          <span>用量</span>
          <span>金额</span>
        </div>

        <!-- 按链路：平铺的四条；按天 / 按课：分组，各组里再分链路 -->
        <template v-if="data.groupBy === 'kind'">
          <div v-for="bucket in flatKinds" :key="bucket.kind" class="cb-table__row">
            <span>{{ kindLabel(bucket.kind) }}</span>
            <span class="mono">{{ bucketText(bucket) || '—' }}</span>
            <span class="mono">{{ formatCost(bucket.estCost) }}</span>
          </div>
        </template>
        <template v-else>
          <div v-for="group in groups" :key="group.key" class="cb-table__row">
            <span class="cb-table__label" :title="group.key">{{ group.label }}</span>
            <span class="cb-table__kinds">{{ kindsText(group.kinds) || '—' }}</span>
            <span class="mono">{{ formatCost(group.estCost) }}</span>
          </div>
        </template>
      </div>

      <p class="cb-note">{{ data.note }}（{{ data.from }} ~ {{ data.to }}）</p>
    </template>
  </section>
</template>

<style scoped>
.cb-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.cb-hint {
  font-size: 13px;
  color: var(--td-text-placeholder);
}

.cb-hint.is-error {
  color: var(--td-error-color);
}

.cb-kinds {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}

.cb-kind {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid var(--td-component-border);
  border-radius: var(--td-radius-medium);
  background: var(--td-bg-secondarycontainer);
}

.cb-kind__name {
  font-size: 12px;
  color: var(--td-text-secondary);
}

.cb-kind__cost {
  font-size: 17px;
  font-weight: 600;
}

.cb-kind__meta {
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.cb-total {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-top: 12px;
  font-size: 13px;
}

.cb-total .mono {
  font-size: 15px;
  font-weight: 600;
}

.cb-total__meta {
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.cb-warn {
  margin-top: 8px;
  font-size: 12px;
  color: var(--td-warning-color);
}

.cb-table {
  margin-top: 14px;
  border-top: 1px solid var(--td-component-stroke);
}

.cb-table__head,
.cb-table__row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(140px, 1.2fr) 90px;
  gap: 10px;
  padding: 6px 0;
  font-size: 13px;
  align-items: baseline;
}

.cb-table__head {
  font-size: 12px;
  color: var(--td-text-placeholder);
  border-bottom: 1px solid var(--td-component-stroke);
}

.cb-table__row {
  border-bottom: 1px dashed var(--td-component-stroke);
}

.cb-table__row > span:last-child {
  text-align: right;
}

.cb-table__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cb-table__kinds {
  font-size: 12px;
  color: var(--td-text-secondary);
}

.cb-note {
  margin-top: 10px;
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.mono {
  font-family: var(--td-font-mono);
}
</style>
