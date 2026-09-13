<script setup lang="ts">
/**
 * 工作台左栏：**课程大纲**（P1-A3）。
 *
 * 这一栏原先叫 `ChatPanel`，装着会话、任务卡和一棵折叠的大纲树 —— 三样东西
 * 抢 380px 宽的地方，大纲树展开还被限在 40vh，看不全。现在会话整体搬到了
 * 右下角的 `AgentFloat`，这一栏只剩大纲：树撑满整列，滚起来才像棵树。
 *
 * 顶部那行字是**课程身份**（`sessionLine` 照抄大纲接口），不是前端自己编的
 * 「已连接」之类（P1-B5）。大纲树本体由外面通过默认插槽送进来 ——
 * 那一堆增删改序要用 `useOutlineDraft`，是工作台的状态，不是这一栏的。
 */
defineProps<{
  /** 顶栏那行「这是哪门课」：课程标题 · 状态 · 页数。 */
  sessionLine: string
  /** 页数小字。 */
  outlineSummary: string
  /** 本地改过还没提交（「确认大纲」之前）。 */
  outlineDirty: boolean
}>()
</script>

<template>
  <section class="wb-outline">
    <header class="wb-outline__title">
      <div class="wb-outline__id">
        <h3>课程大纲</h3>
        <p :title="sessionLine">{{ sessionLine }}</p>
      </div>
      <span class="spacer" />
      <span v-if="outlineSummary" class="wb-outline__count">{{ outlineSummary }}</span>
      <t-tag v-if="outlineDirty" theme="warning" variant="light" size="small">未提交</t-tag>
    </header>

    <div class="wb-outline__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.wb-outline {
  width: 380px;
  flex-shrink: 0;
  background: var(--td-bg-container);
  border-right: 1px solid var(--td-component-stroke);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.wb-outline__title {
  padding: 14px 16px;
  border-bottom: 1px solid var(--td-component-stroke);
  display: flex;
  align-items: center;
  gap: 8px;
}

.wb-outline__title .spacer {
  flex: 1;
}

.wb-outline__id {
  min-width: 0;
}

.wb-outline__title h3 {
  font-size: 15px;
  font-weight: 600;
}

.wb-outline__title p {
  font-size: 12px;
  color: var(--td-text-placeholder);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 230px;
}

.wb-outline__count {
  font-size: 12px;
  color: var(--td-text-placeholder);
  flex-shrink: 0;
}

/* 树撑满整列并自己滚 —— 不再限高（限高是它与会话挤一块地方时的妥协） */
.wb-outline__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
</style>
