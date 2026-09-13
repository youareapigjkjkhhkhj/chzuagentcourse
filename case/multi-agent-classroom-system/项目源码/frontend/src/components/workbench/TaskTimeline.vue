<script setup lang="ts">
/**
 * 任务时间线（P5-F5-10 / P5-A10）—— 任务卡展开后那一块。
 *
 * 任务卡答的是「现在到哪了」，这一块答的是**「它是怎么走到这儿的」**：
 * 每一步跑了多久、跑了几次、触发了几次模型调用、花了多少 token 与多少钱、
 * 失败在哪一类错误上。数据来自 `GET /api/jobs/{jobId}/timeline`。
 *
 * 三件事是**照抄**服务端的，前端一个都不算：
 *
 * 1. **钱**：金额只算 LLM（`model_calls`），与成本看板同一条口径。语音按量计费、
 *    不挂在这条任务上，所以这里不铺一行假的「本任务语音花费」——响应里的
 *    `note` 把这件事说给用户听。
 * 2. **重试次数**（`attempts`）：累计值，从不归零。「跑过三次才成」和「一次就成」
 *    在界面上必须是两件事，这正是用户该去看上游的那个信号。
 * 3. **进度百分比**：按服务端的权重声明算，与任务卡上那根进度条同一份来源。
 *
 * 组件**挂载即取数**（父组件用 `v-if` 开合），所以每次展开都是新的一份 ——
 * 任务还在跑时展开一次就能看到最新的账，不必额外做轮询。
 */
import { onMounted, ref } from 'vue'

import * as api from '@/api'
import type { JobTimeline, StepCalls } from '@/types/api'
import { formatDurationMs } from '@/utils/format'
import { errorCodeLabel } from '@/utils/labels'
import { formatCost } from '@/utils/voice'

const props = defineProps<{ jobId: string }>()

const data = ref<JobTimeline | null>(null)
const loading = ref(true)
/** 取不到时间线时的一句话。**任务卡本身照常显示** —— 这一块只是详情。 */
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.fetchJobTimeline(props.jobId)
  } catch {
    // 不把原始错误摊在界面上（AGENTS §19）：这一块读取失败不影响任务本身，
    // 给一句「能做什么」比给一串堆栈有用。
    data.value = null
    error.value = '时间线读取失败，稍后再试'
  } finally {
    loading.value = false
  }
}

onMounted(load)

/** 一步的账 → 一行小字。没有调用过的步骤（装配、被跳过的语音）如实说「无调用」。 */
function callsLine(calls: StepCalls): string {
  if (!calls.count) return '无模型调用'
  const bits = [`${calls.count} 次调用`]
  if (calls.tokens) bits.push(`${calls.tokens} tokens`)
  if (calls.estCost) bits.push(formatCost(calls.estCost))
  // 失败的那几次**也在** count 里：`2 次调用（1 次失败）` 比 `1 次调用` 有用
  if (calls.failed) bits.push(`${calls.failed} 次失败`)
  return bits.join(' · ')
}

/** 耗时。还没跑完的步骤是 0 —— 显示「—」而不是「<1s」。 */
function timeText(ms: number): string {
  return formatDurationMs(ms) || '—'
}

/** 用一个 token / 金额口径解释「这一步贵不贵」，铺在展开区的页脚。 */
function totalLine(): string {
  const current = data.value
  if (!current) return ''
  const bits = [`合 ${current.totals.steps} 步`]
  if (current.totals.attempts > current.totals.steps) {
    // 只有真的重跑过才提这一句：每步都只跑一次时，「共 6 次」是噪声
    bits.push(`共跑了 ${current.totals.attempts} 次`)
  }
  if (current.totals.retriedSteps) bits.push(`${current.totals.retriedSteps} 步重试过`)
  if (current.totals.failedSteps) bits.push(`${current.totals.failedSteps} 步失败`)
  bits.push(`累计耗时 ${formatDurationMs(current.totals.stepMs) || '—'}`)
  bits.push(callsLine(current.totals.calls))
  return bits.filter(Boolean).join(' · ')
}
</script>

<template>
  <div class="tl">
    <p v-if="loading" class="tl-hint">正在读取时间线…</p>
    <p v-else-if="error" class="tl-hint is-error">{{ error }}</p>

    <template v-else-if="data">
      <div v-for="step in data.steps" :key="step.id" class="tl-row">
        <span class="tl-name">{{ step.title }}</span>
        <span class="tl-time mono">{{ timeText(step.durationMs) }}</span>
        <t-tag
          v-if="step.attempts > 1"
          size="small"
          variant="light"
          theme="warning"
          :title="`这一步一共跑过 ${step.attempts} 次（含重试与续跑）`"
        >
          跑过 {{ step.attempts }} 次
        </t-tag>
        <t-tag v-if="step.errorCode" size="small" variant="light" theme="danger">
          {{ errorCodeLabel(step.errorCode) }}
        </t-tag>
        <span class="tl-calls mono">{{ callsLine(step.calls) }}</span>
        <span v-if="step.calls.models.length" class="tl-model mono">
          {{ step.calls.models.join(' / ') }}
        </span>
      </div>

      <p class="tl-total">{{ totalLine() }}</p>

      <!--
        认不出归属的调用：正常跑不会出现，出现了一定是哪里漏了 step_id。
        与其把它悄悄并进合计，不如让它单独露一行 —— token 对不上账时，
        这是第一个该看的地方。
      -->
      <p v-if="data.totals.unattributed.count" class="tl-orphan">
        另有 {{ data.totals.unattributed.count }} 次调用没归到任何一步上（
        {{ callsLine(data.totals.unattributed) }}）
      </p>

      <p class="tl-note">{{ data.note }}</p>
    </template>
  </div>
</template>

<style scoped>
.tl {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--td-component-stroke);
  font-size: 12px;
}

.tl-hint {
  color: var(--td-text-placeholder);
}

.tl-hint.is-error {
  color: var(--td-error-color);
}

.tl-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  flex-wrap: wrap;
}

.tl-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--td-text-secondary);
}

.tl-time {
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.tl-calls {
  font-size: 11px;
  color: var(--td-text-placeholder);
  flex-basis: 100%;
  padding-left: 2px;
}

.tl-model {
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.tl-total {
  margin-top: 8px;
  color: var(--td-text-secondary);
}

.tl-orphan {
  margin-top: 6px;
  color: var(--td-warning-color);
}

.tl-note {
  margin-top: 6px;
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.mono {
  font-family: var(--td-font-mono);
}
</style>
