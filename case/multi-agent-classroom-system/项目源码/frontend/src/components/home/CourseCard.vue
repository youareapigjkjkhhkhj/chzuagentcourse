<script setup lang="ts">
/**
 * 「最近课堂」的一张卡片（版式照 `产品原型/index.html` 的 `.course-card`）。
 *
 * 卡片上的每个数字都是接口给的（P1-A10）：页数、时长、进度、状态。
 * 组件不算也不猜 —— 生成中的百分比就是 `courses` 行上那个 `progress`。
 */
import { computed } from 'vue'

import type { CourseCard } from '@/types/api'
import { formatMinutes, formatPages, formatRelativeTime } from '@/utils/format'
import { COURSE_STATUS_LABELS, COURSE_STATUS_THEMES } from '@/utils/labels'

const props = defineProps<{
  course: CourseCard
  index: number
}>()

const emit = defineEmits<{
  open: []
  remove: []
}>()

/** 封面四选一，按顺序轮着来（原型是 cover-1..4 四张渐变）。 */
const coverClass = computed(() => `cover-${(props.index % 4) + 1}`)
const coverNo = computed(() => String(props.index + 1).padStart(2, '0'))

const statusText = computed(() =>
  props.course.status === 'generating'
    ? `${COURSE_STATUS_LABELS.generating} ${props.course.progress}%`
    : COURSE_STATUS_LABELS[props.course.status],
)

const updatedText = computed(() => formatRelativeTime(props.course.updatedAt))
</script>

<template>
  <div class="t-card course-card" @click="emit('open')">
    <div class="course-card__cover" :class="coverClass">
      <span class="cover-no">{{ coverNo }}</span>
      <div class="cover-title">{{ course.title }}</div>
    </div>
    <div class="course-card__body">
      <div class="course-card__meta">
        <span>{{ formatPages(course.pageCount) }}</span>
        <span>·</span>
        <span>{{ formatMinutes(course.durationMin) }}</span>
        <template v-if="updatedText">
          <span>·</span>
          <span>{{ updatedText }}</span>
        </template>
      </div>
      <div class="course-card__foot">
        <t-tag :theme="COURSE_STATUS_THEMES[course.status]" variant="light">
          {{ statusText }}
        </t-tag>
        <span class="text-placeholder roles">1 教师 · {{ course.roleCount }} 同学</span>
        <t-popconfirm content="删除后列表里不再显示（页面与版本仍留在库里）" @confirm="emit('remove')">
          <button class="course-card__del" title="删除这门课" @click.stop>删除</button>
        </t-popconfirm>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 版式取自 产品原型/index.html 的 .course-card */
.course-card {
  overflow: hidden;
  cursor: pointer;
  transition:
    box-shadow 0.25s,
    transform 0.25s;
}

.course-card:hover {
  box-shadow: var(--td-shadow-2);
  transform: translateY(-3px);
}

.course-card__cover {
  position: relative;
  height: 148px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.course-card__cover .cover-title {
  color: #fff;
  font-size: 17px;
  font-weight: 600;
  line-height: 1.4;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
}

.course-card__cover .cover-no {
  position: absolute;
  top: 14px;
  right: 16px;
  color: rgba(255, 255, 255, 0.55);
  font-size: 34px;
  font-weight: 700;
  font-family: Georgia, serif;
}

.cover-1 {
  background: linear-gradient(135deg, #0052d9 0%, #366ef4 55%, #618eff 100%);
}

.cover-2 {
  background: linear-gradient(135deg, #0c7a5b 0%, #00a870 60%, #33c68f 100%);
}

.cover-3 {
  background: linear-gradient(135deg, #c25710 0%, #ed7b2f 60%, #f5a06b 100%);
}

.cover-4 {
  background: linear-gradient(135deg, #4a3fb5 0%, #6a5fd0 60%, #948be0 100%);
}

.course-card__body {
  padding: 14px 16px 16px;
}

.course-card__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.course-card__foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

.course-card__foot .roles {
  margin-left: auto;
  font-size: 12px;
}

.course-card__del {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 12px;
  color: var(--td-text-placeholder);
  cursor: pointer;
}

.course-card__del:hover {
  color: var(--td-error-color);
}
</style>
