<script setup lang="ts">
/**
 * 工作台左栏：生成任务（版式照 `产品原型/workbench.html` 的左侧会话列）。
 *
 * 这一栏**只读**：进度、步骤、实时页号都是 `useGenerationStream` 从服务端
 * 那儿拿来的（P1-B5），本组件一不造数二不改数，只把两件事交回去 ——
 * 「取消这次生成」和「重试某一步」，动作本身由工作台去做。
 *
 * 单独拆出来的理由很实际：这一栏从头到尾不碰大纲状态，凡是碰大纲的东西
 * （选中页、删页、确认）都在外面，两边的耦合是零。
 */
import TaskCard from '@/components/workbench/TaskCard.vue'
import type { JobStatus, LiveStep, WriteBatch } from '@/types/api'

/** 头像渐变取自原型（原型是内联 style，这里按角色收成常量）。 */
const AGENT_AVATAR = 'linear-gradient(135deg,#0052d9,#618eff)'

defineProps<{
  /** 顶栏那行「谁在服务」：课程标题 · 状态 · 页数，照抄大纲接口。 */
  sessionLine: string
  jobId: string
  steps: LiveStep[]
  batches: WriteBatch[]
  percent: number | null
  status: JobStatus | ''
  canceled: boolean
  error: string
  /** 进度是推来的还是回问来的，如实写一行。 */
  linkLine: string
}>()

const emit = defineEmits<{
  cancel: []
  retry: [stepId: string]
}>()
</script>

<template>
  <section class="wb-chat">
    <div class="wb-chat__head">
      <t-avatar :style="{ background: AGENT_AVATAR }" shape="circle">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8">
          <path
            d="M12 3l1.8 4.7L18.5 9l-4.7 1.8L12 15.5l-1.8-4.7L5.5 9l4.7-1.3L12 3ZM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z"
          />
        </svg>
      </t-avatar>
      <div class="wb-chat__id">
        <h3>课程生成 Agent</h3>
        <p>{{ sessionLine }}</p>
      </div>
    </div>

    <div class="wb-msgs">
      <TaskCard
        v-if="jobId"
        :steps="steps"
        :batches="batches"
        :percent="percent"
        :status="status"
        :canceled="canceled"
        :error="error"
        @cancel="emit('cancel')"
        @retry="emit('retry', $event)"
      />
      <div v-else class="wb-empty">
        <t-empty
          title="还没有选择课程"
          description="回首页输入一个主题就能开工；生成中随时可以在中间那列改大纲。"
        />
      </div>

      <p v-if="jobId" class="wb-link">{{ linkLine }}</p>
    </div>
  </section>
</template>

<style scoped>
/* --- 左：生成任务 --- */

.wb-chat {
  width: 360px;
  flex-shrink: 0;
  background: var(--td-bg-container);
  border-right: 1px solid var(--td-component-stroke);
  display: flex;
  flex-direction: column;
}

.wb-chat__head {
  padding: 14px 16px;
  border-bottom: 1px solid var(--td-component-stroke);
  display: flex;
  align-items: center;
  gap: 10px;
}

.wb-chat__head .t-avatar {
  flex-shrink: 0;
}

.wb-chat__id {
  min-width: 0;
}

.wb-chat__head h3 {
  font-size: 15px;
  font-weight: 600;
}

.wb-chat__head p {
  font-size: 12px;
  color: var(--td-text-placeholder);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wb-msgs {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--td-bg-page);
}

.wb-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.wb-link {
  font-size: 12px;
  color: var(--td-text-placeholder);
  padding-left: 2px;
}
</style>
