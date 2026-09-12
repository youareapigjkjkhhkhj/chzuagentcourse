<script setup lang="ts">
/**
 * 课堂左侧舞台：幻灯片 + 教具 + 字幕 + 播放控制。
 *
 * 版式取自 `产品原型/classroom.html`。有课就按页放映 —— 幻灯片、讲稿、页数
 * 都在 P1 落库了，翻页本来就不需要课堂运行时，之前这一页只是个空壳。
 *
 * 仍然不假装的部分：字幕条放的是**当前页的讲稿**而不是「正在念的话」（没有
 * 音频就不假装在念），教具只到选中，播放键与进度条如实标着 P3 接入。
 */
import { computed, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

import PageSlide from '@/components/workbench/PageSlide.vue'
import { useSettingsStore } from '@/stores/settings'
import type { CoursePageItem } from '@/types/api'

const props = withDefaults(
  defineProps<{
    page?: CoursePageItem | null
    courseTitle?: string
    /** 整门课的页数，照服务端那份（翻页只看得到已生成的页） */
    pageCount?: number
    canPrev?: boolean
    canNext?: boolean
    loading?: boolean
    /** 空状态的标题与说明由页面给：没选课、正在读、读失败，说法不一样 */
    emptyTitle?: string
    emptyText?: string
  }>(),
  {
    page: null,
    courseTitle: '',
    pageCount: 0,
    canPrev: false,
    canNext: false,
    loading: false,
    emptyTitle: '还没有可讲授的课程',
    emptyText: '',
  },
)

const emit = defineEmits<{ prev: []; next: [] }>()

const settings = useSettingsStore()

const TOOLS = [
  { key: 'laser', title: '激光笔' },
  { key: 'spotlight', title: '聚光灯' },
  { key: 'pen', title: '画笔' },
  { key: 'eraser', title: '橡皮擦' },
] as const

const activeTool = ref<string>('')

function pickTool(title: string) {
  activeTool.value = title
  MessagePlugin.info(`已选中「${title}」——标注能力随课堂运行时在 P3 接入`)
}

/** 字幕条：这一页的讲稿。没有就说明它为什么空着，不编一句台词。 */
const subtitle = computed(() => {
  const beats = props.page?.dsl.narration ?? []
  if (beats.length) return beats.map((beat) => beat.text).join(' ')
  if (props.loading) return '正在读取这门课…'
  return 'AI 教师的语音讲解字幕会出现在这里 —— 语音合成（TTS）在 P2 阶段接入。'
})
</script>

<template>
  <div class="stage-wrap">
    <div class="stage">
      <PageSlide
        v-if="page"
        variant="classroom"
        :page="page"
        :course-title="courseTitle"
        :page-count="pageCount"
      />
      <div v-else class="slide">
        <t-empty :title="emptyTitle" :description="emptyText" />
      </div>

      <div class="stage-tools">
        <span
          v-for="tool in TOOLS"
          :key="tool.key"
          class="tool"
          :class="{ 'is-active': activeTool === tool.title }"
          :title="tool.title"
          @click="pickTool(tool.title)"
        >
          <svg
            v-if="tool.key === 'laser'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
          >
            <circle cx="12" cy="12" r="3" />
            <circle cx="12" cy="12" r="7" stroke-dasharray="3 3" />
          </svg>
          <svg
            v-else-if="tool.key === 'spotlight'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
          >
            <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.8.7 1 1.5 1 2.5h6c0-1 .2-1.8 1-2.5A6 6 0 0 0 12 3Z" />
          </svg>
          <svg
            v-else-if="tool.key === 'pen'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
          >
            <path d="m14 6 4 4L8.5 19.5a2.1 2.1 0 0 1-3-3L14 6ZM13 7l4 4M16 4l4 4" />
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="m9 15 8.5-8.5a2.1 2.1 0 0 1 3 3L12 18H8l-3 3h13" />
          </svg>
        </span>
        <span
          class="tool"
          title="清除标注"
          @click="MessagePlugin.info('清除标注随课堂运行时在 P3 接入')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path
              d="M4 7h16M10 11v6M14 11v6M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M9 7V4h6v3"
            />
          </svg>
        </span>
      </div>
    </div>

    <!-- 字幕条：这一页的讲稿 -->
    <div class="subtitle">
      <span class="who">{{ settings.teacher?.name ?? 'AI 教师' }}</span>
      <span class="text">{{ subtitle }}</span>
    </div>

    <!-- 播放控制 -->
    <div class="player-bar">
      <button
        class="play-btn"
        title="播放"
        @click="MessagePlugin.info('课堂播放控制随课堂运行时在 P3 接入')"
      >
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l11-6.5-11-6.5Z" /></svg>
      </button>
      <t-button variant="outline" :disabled="!canPrev" @click="emit('prev')">
        <template #icon>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M15 5l-7 7 7 7" />
          </svg>
        </template>
        上一页
      </t-button>
      <span class="page-indicator">
        第 <b>{{ page?.pageNo ?? '—' }}</b> / {{ pageCount || '—' }} 页
      </span>
      <t-button variant="outline" :disabled="!canNext" @click="emit('next')">
        下一页
        <template #suffix>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M9 5l7 7-7 7" />
          </svg>
        </template>
      </t-button>
      <div class="player-progress">
        <span class="mono">--:--</span>
        <t-progress :percentage="0" :label="false" />
        <span class="mono">--:--</span>
      </div>
      <t-button variant="text" @click="MessagePlugin.info('倍速随课堂运行时在 P3 接入')">
        1.0x
      </t-button>
    </div>
  </div>
</template>

<style scoped>
.stage-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 20px 20px 0;
  min-width: 0;
  background: var(--td-bg-page);
}

.stage {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
}

.slide {
  position: relative;
  width: 100%;
  max-width: 960px;
  aspect-ratio: 16 / 9;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-2);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

/* 教具工具条：浮在幻灯片右侧 */
.stage-tools {
  position: absolute;
  right: 24px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-2);
  padding: 6px;
}

.stage-tools .tool {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--td-radius-default);
  cursor: pointer;
  color: var(--td-text-secondary);
  transition: all 0.2s;
}

.stage-tools .tool:hover {
  background: var(--td-bg-container-hover);
  color: var(--td-text-primary);
}

.stage-tools .tool.is-active {
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
}

.stage-tools .tool svg {
  width: 18px;
  height: 18px;
}

/* 字幕条 */
.subtitle {
  margin: 14px auto 0;
  max-width: 820px;
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: var(--td-bg-container);
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--td-radius-medium);
  padding: 10px 16px;
  font-size: 14px;
  line-height: 1.7;
  box-shadow: var(--td-shadow-1);
}

.subtitle .who {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--td-brand-color);
}

.subtitle .text {
  color: var(--td-text-secondary);
}

/* 播放控制条 */
.player-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 14px 0 16px;
  padding: 10px 18px;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
}

.page-indicator {
  font-size: 13px;
  color: var(--td-text-secondary);
  min-width: 86px;
  text-align: center;
}

.page-indicator b {
  color: var(--td-text-placeholder);
  font-family: var(--td-font-mono);
  font-size: 15px;
}

.play-btn {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  background: var(--td-brand-color);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
  flex-shrink: 0;
}

.play-btn:hover {
  background: var(--td-brand-color-hover);
}

.play-btn svg {
  width: 17px;
  height: 17px;
}

.player-progress {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.player-progress :deep(.t-progress) {
  flex: 1;
}
</style>
