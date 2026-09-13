<script setup lang="ts">
/**
 * 生成任务卡（版式照 `产品原型/workbench.html` 的 `.task-card`）。
 *
 * **屏幕上的进度只有两个来源**：SSE 的帧，或者 `GET /api/jobs/{jobId}` 的响应
 * （P1-B5）。所以 `percent` 为 `null` 时显示的是「—」——「还不知道」和「0%」
 * 是两件事，前者不该画成一根会自己爬的进度条。
 */
import { computed, ref } from 'vue'

import TaskTimeline from '@/components/workbench/TaskTimeline.vue'
import type { JobStatus, LiveStep, WriteBatch } from '@/types/api'
import { formatDurationMs } from '@/utils/format'
import { JOB_STATUS_LABELS, STEP_CLASSES } from '@/utils/labels'

const props = defineProps<{
  jobId: string
  steps: LiveStep[]
  /** 写页那一步分批的子进度（服务端在 `step.progress` 里带过来的）。 */
  batches: WriteBatch[]
  /** 服务端给的百分比；`null` = 一份数据都还没拿到。 */
  percent: number | null
  status: JobStatus | ''
  canceled: boolean
  error: string
  /**
   * 能不能「继续生成」（P5-F5-9）。**由服务端判**：停下来了（失败 / 取消 /
   * 被重启打断）且还有没跑完的步骤。前端自己拼 `status === 'failed'`
   * 会漏掉后两种，而它们恰恰是最该续的。
   */
  resumable: boolean
}>()

const emit = defineEmits<{
  cancel: []
  retry: [stepId: string]
  resume: []
}>()

const TERMINAL: readonly string[] = ['done', 'failed', 'canceled']

const percentText = computed(() => (props.percent === null ? '—' : `${props.percent}%`))

/** 任务已经结束（或被取消）就没有「取消」可点了。 */
const canCancel = computed(() => !props.canceled && !TERMINAL.includes(props.status))

/**
 * 时间线收不收起来。**默认收起**：任务卡的第一眼要留给进度本身，
 * 「钱花在哪一步」是点开才看的东西。展开时组件才挂载，于是每次展开都是新取的数。
 */
const timelineOpen = ref(false)

const statusText = computed(() => {
  if (props.canceled) return '已取消'
  if (props.error) return props.error
  return props.status ? JOB_STATUS_LABELS[props.status] : '等待开始'
})

/**
 * 分批子进度挂在哪一步下面。
 *
 * P1 只有「写页」那一步会分批（服务端在 `step.progress` 的 `detail.batches`
 * 里带过来），所以这里按步骤类型认领，而不是另开一张步骤与批次的对应表 ——
 * 那张表迟早会和步骤本身的顺序对不上。
 */
function batchesOf(step: LiveStep): WriteBatch[] {
  return step.type === 'write' ? props.batches : []
}

/** 一批写了多少页 → 进度条宽度。批里的页数是服务端给的，前端只做除法。 */
function batchWidth(batch: WriteBatch): string {
  const total = Math.max(1, batch.total)
  return `${Math.round((batch.done / total) * 100)}%`
}
</script>

<template>
  <div class="task-card">
    <h4>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M9 11l3 3L22 4" />
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
      </svg>
      生成任务
    </h4>

    <div v-for="step in steps" :key="step.id" class="task-step" :class="STEP_CLASSES[step.status]">
      <span class="st-ico">
        <svg
          v-if="step.status === 'done'"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="3"
        >
          <path d="M20 6 9 17l-5-5" />
        </svg>
      </span>
      <span class="st-title">{{ step.title }}</span>
      <span class="st-time">{{ formatDurationMs(step.durationMs) }}</span>
      <button v-if="step.status === 'failed'" class="st-retry" @click="emit('retry', step.id)">
        重试
      </button>
      <p v-if="step.error" class="st-error">{{ step.error }}</p>

      <div
        v-for="batch in batchesOf(step)"
        :key="batch.label"
        class="task-batch"
        :class="`is-${batch.status}`"
      >
        <span class="batch-bar"><i :style="{ width: batchWidth(batch) }" /></span>
        <span class="batch-label">{{ batch.label }}</span>
        <span class="batch-count mono">{{ batch.done }}/{{ batch.total }}</span>
      </div>
    </div>

    <div class="task-card__progress">
      <div class="progress__line">
        <span>总进度</span>
        <span class="wb-progress mono">{{ percentText }}</span>
      </div>
      <t-progress :percentage="percent ?? 0" :label="false" theme="line" />
    </div>

    <div class="task-card__foot">
      <t-tag :theme="status === 'failed' ? 'danger' : 'default'" variant="light" size="small">
        {{ statusText }}
      </t-tag>
      <div class="task-card__acts">
        <!--
          断点续跑：从第一个没做完的步骤接着跑，已经写好的页面一页都不重写。
          与「重试」不是一回事 —— 那个是用户指着某一步说再来一次，
          这个是「接着上次的地方往下跑」，断点由服务端从状态里自己找。
        -->
        <t-button
          v-if="resumable"
          class="wb-resume"
          size="small"
          theme="primary"
          variant="outline"
          @click="emit('resume')"
        >
          继续生成
        </t-button>
        <t-button
          v-if="canCancel"
          class="wb-cancel"
          size="small"
          variant="outline"
          @click="emit('cancel')"
        >
          取消生成
        </t-button>
      </div>
    </div>

    <button class="task-card__toggle" type="button" @click="timelineOpen = !timelineOpen">
      {{ timelineOpen ? '收起时间线' : '查看时间线' }}
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        :class="{ 'is-open': timelineOpen }"
      >
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>
    <TaskTimeline v-if="timelineOpen" :job-id="jobId" />
  </div>
</template>

<style scoped>
/* 版式取自 产品原型/workbench.html 的 .task-card / .task-step */
.task-card {
  background: var(--td-bg-container);
  border: 1px solid var(--td-component-border);
  border-radius: var(--td-radius-medium);
  padding: 14px;
  box-shadow: var(--td-shadow-1);
}

.task-card h4 {
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
}

.task-card h4 svg {
  width: 15px;
  height: 15px;
  color: var(--td-brand-color);
}

.task-step {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  font-size: 13px;
  flex-wrap: wrap;
}

.task-step .st-title {
  flex: 1;
  min-width: 0;
}

.task-step .st-ico {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-sizing: border-box;
}

.task-step .st-ico svg {
  width: 12px;
  height: 12px;
}

.task-step.is-done .st-ico {
  background: var(--td-success-color-light);
  color: var(--td-success-color);
}

.task-step.is-done {
  color: var(--td-text-secondary);
}

.task-step.is-running {
  color: var(--td-brand-color);
  font-weight: 500;
}

.task-step.is-running .st-ico {
  border: 2px solid var(--td-brand-color-focus);
  border-top-color: var(--td-brand-color);
  animation: spin 0.9s linear infinite;
}

.task-step.is-waiting {
  color: var(--td-text-placeholder);
}

.task-step.is-waiting .st-ico {
  border: 1px solid var(--td-component-border);
}

.task-step.is-failed {
  color: var(--td-error-color);
}

.task-step.is-failed .st-ico {
  border: 2px solid var(--td-error-color);
}

.task-step.is-skipped {
  color: var(--td-text-placeholder);
  text-decoration: line-through;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.task-step .st-time {
  margin-left: auto;
  font-size: 11px;
  color: var(--td-text-placeholder);
  font-family: var(--td-font-mono);
}

.task-step .st-retry {
  border: 1px solid var(--td-component-border);
  background: transparent;
  border-radius: var(--td-radius-default);
  padding: 1px 8px;
  font-size: 11px;
  color: var(--td-text-secondary);
  cursor: pointer;
}

.task-step .st-retry:hover {
  border-color: var(--td-brand-color);
  color: var(--td-brand-color);
}

.task-step .st-error {
  flex-basis: 100%;
  font-size: 12px;
  color: var(--td-error-color);
  padding-left: 30px;
}

/* 写页那一步下面的分批子进度（原型上是缩进的两行） */
.task-batch {
  flex-basis: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0 3px 30px;
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.task-batch .batch-bar {
  width: 46px;
  height: 4px;
  border-radius: 2px;
  background: var(--td-bg-container-active);
  overflow: hidden;
  flex-shrink: 0;
}

.task-batch .batch-bar i {
  display: block;
  height: 100%;
  background: var(--td-brand-color);
  transition: width 0.2s;
}

.task-batch.is-done .batch-bar i {
  background: var(--td-success-color);
}

.task-batch.is-failed .batch-bar i {
  background: var(--td-error-color);
}

.task-batch .batch-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-batch .batch-count {
  font-size: 11px;
}

.task-card__progress {
  margin-top: 10px;
}

.progress__line {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--td-text-secondary);
  margin-bottom: 6px;
}

.mono {
  font-family: var(--td-font-mono);
}

.task-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 12px;
}

.task-card__acts {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-card__toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 10px;
  padding: 0;
  border: none;
  background: transparent;
  font-size: 12px;
  color: var(--td-text-secondary);
  cursor: pointer;
}

.task-card__toggle:hover {
  color: var(--td-brand-color);
}

.task-card__toggle svg {
  width: 12px;
  height: 12px;
  transition: transform 0.15s;
}

.task-card__toggle svg.is-open {
  transform: rotate(180deg);
}
</style>
