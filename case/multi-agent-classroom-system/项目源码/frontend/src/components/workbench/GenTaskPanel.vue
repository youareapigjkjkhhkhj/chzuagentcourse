<script setup lang="ts">
/**
 * **生成任务卡**（版式照 `产品原型/workbench.html` 左侧会话列里那张卡）。
 *
 * 它画在这次生成的头上，因为它确实只是这次对话的一条消息：「帮我生成一门课」
 * 之后 Agent 交出来的东西。外框（标题、页签、收起）在 `AgentFloat` 那边 ——
 * 那些是**那个框**的结构，而六步进度是**这一次生成**的状态，生命周期不一样。
 *
 * 这一块**只读**：进度、步骤、实时页号都是 `useGenerationStream` 从服务端
 * 那儿拿来的（P1-B5），本组件一不造数二不改数，只把两件事交回去 ——
 * 「取消这次生成」和「重试某一步」，动作本身由工作台去做。
 */
import TaskCard from '@/components/workbench/TaskCard.vue'
import type { JobStatus, LiveStep, WriteBatch } from '@/types/api'

defineProps<{
  jobId: string
  steps: LiveStep[]
  batches: WriteBatch[]
  percent: number | null
  status: JobStatus | ''
  canceled: boolean
  error: string
  /** 断点续跑：「继续生成」按钮亮不亮，由服务端判（P5-F5-9）。 */
  resumable: boolean
  /** 进度是推来的还是回问来的，如实写一行。 */
  linkLine: string
}>()

const emit = defineEmits<{
  cancel: []
  retry: [stepId: string]
  resume: []
}>()
</script>

<template>
  <!-- 没有生成任务就什么都不画：那个空态由 AgentFloat 说（它才知道有没有课） -->
  <div v-if="jobId" class="wb-task">
    <TaskCard
      :job-id="jobId"
      :steps="steps"
      :batches="batches"
      :percent="percent"
      :status="status"
      :canceled="canceled"
      :error="error"
      :resumable="resumable"
      @cancel="emit('cancel')"
      @retry="emit('retry', $event)"
      @resume="emit('resume')"
    />
    <p class="wb-link">{{ linkLine }}</p>
  </div>
</template>

<style scoped>
.wb-task {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.wb-link {
  font-size: 12px;
  color: var(--td-text-placeholder);
  padding-left: 2px;
}
</style>
