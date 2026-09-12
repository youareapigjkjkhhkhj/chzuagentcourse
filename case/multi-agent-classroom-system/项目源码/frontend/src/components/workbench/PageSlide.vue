<script setup lang="ts">
/**
 * 幻灯片预览（版式照 `产品原型/workbench.html` 的 `.preview__slide`，16:9）。
 *
 * 只读：它显示的是**服务端那份** —— 编辑框里改了还没保存的内容不会先跑上来，
 * 「预览和实际不一致」比「预览慢半拍」难查得多。
 *
 * 讲稿（`narration`）也画在这里：讲台上看到的提示词和幻灯片是一体的，
 * 拆到两个面板反而要在两处对页号。
 */
import { computed } from 'vue'

import type { CoursePageItem, SlideDsl } from '@/types/api'
import { PAGE_KIND_LABELS, visualTypeLabel } from '@/utils/labels'

const props = withDefaults(
  defineProps<{
    page: CoursePageItem | null
    courseTitle: string
    pageCount: number
    /**
     * `classroom` = 课堂舞台那一份：只要幻灯片本体。
     * 讲稿在那边由字幕条承担，底下那句「右侧可改讲稿与标题」在课堂页也不成立。
     */
    variant?: 'workbench' | 'classroom'
  }>(),
  { variant: 'workbench' },
)

const dsl = computed<SlideDsl>(() => props.page?.dsl ?? {})
const narration = computed(() => dsl.value.narration ?? [])
/** 课堂舞台那一份不带工作台的侧栏提示 —— 那边根本没有「右侧」。 */
const onStage = computed(() => props.variant === 'classroom')
</script>

<template>
  <div class="page-slide" :class="{ 'is-stage': onStage }">
    <div v-if="page" class="preview__slide">
      <div class="slide-head">
        第 {{ page.pageNo }} 页 · {{ PAGE_KIND_LABELS[page.kind] }}
      </div>
      <h3 class="slide-title">
        {{ dsl.title }}
        <small v-if="dsl.subtitle">{{ dsl.subtitle }}</small>
      </h3>

      <ul v-if="dsl.bullets?.length" class="slide-bullets">
        <li v-for="(bullet, index) in dsl.bullets" :key="index">{{ bullet.text }}</li>
      </ul>

      <div v-if="dsl.code" class="slide-code">
        <pre>{{ dsl.code.content }}</pre>
        <span v-if="dsl.code.lang" class="slide-code__lang">{{ dsl.code.lang }}</span>
      </div>

      <div v-if="dsl.visual" class="slide-visual">
        <span class="slide-visual__type">{{ visualTypeLabel(dsl.visual.type) }}</span>
        <span>{{ dsl.visual.desc }}</span>
      </div>

      <div v-if="dsl.quiz" class="slide-quiz">
        <p class="quiz-stem">{{ dsl.quiz.stem }}</p>
        <ol class="quiz-options">
          <li v-for="(option, index) in dsl.quiz.options" :key="index">{{ option }}</li>
        </ol>
      </div>

      <p v-if="dsl.question" class="slide-question">{{ dsl.question }}</p>
      <p v-if="dsl.topic" class="slide-question">{{ dsl.topic }}</p>
      <ul v-if="dsl.sides?.length" class="slide-bullets">
        <li v-for="(side, index) in dsl.sides" :key="index">{{ side.stance }}</li>
      </ul>

      <div class="slide-foot">
        <span>{{ courseTitle }} · EduAgentX</span>
        <span>{{ String(page.pageNo).padStart(2, '0') }} / {{ pageCount }}</span>
      </div>
    </div>

    <div v-else class="preview__slide is-empty">
      <t-empty title="还没有可预览的页面" description="在左边的大纲里选一页" />
    </div>

    <div v-if="narration.length && !onStage" class="slide-notes">
      <h5>讲稿</h5>
      <p v-for="(beat, index) in narration" :key="index" class="beat">
        <span class="beat-no">{{ index + 1 }}</span>
        {{ beat.text }}
      </p>
    </div>

    <div v-if="!onStage" class="preview__hint">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8h.01M12 11v5" />
      </svg>
      预览为只读 · 显示的是服务端已保存的那一版，右侧可改讲稿与标题
    </div>
  </div>
</template>

<style scoped>
/* 版式取自 产品原型/workbench.html 的 .preview */
.page-slide {
  flex: 1;
  min-width: 0;
}

/*
 * 课堂舞台那一份：外框由它自己定（同样 16:9、同样 960 上限），
 * 因为舞台里没有 `.preview__slide` 那一层同尺寸的容器可以借。
 */
.page-slide.is-stage {
  flex: none;
  width: 100%;
  max-width: 960px;
  aspect-ratio: 16 / 9;
  display: flex;
}

.page-slide.is-stage .preview__slide {
  flex: 1;
  box-shadow: var(--td-shadow-2);
}

.preview__slide {
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
  aspect-ratio: 16 / 9;
  padding: 36px 44px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.preview__slide.is-empty {
  align-items: center;
  justify-content: center;
}

.slide-head {
  font-size: 12px;
  color: var(--td-brand-color);
  font-weight: 600;
  letter-spacing: 2px;
  margin-bottom: 8px;
}

.slide-title {
  font-size: 24px;
  font-weight: 600;
}

.slide-title small {
  display: block;
  font-size: 13px;
  color: var(--td-text-secondary);
  font-weight: 400;
  margin-top: 6px;
}

.slide-bullets {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 22px;
  font-size: 14px;
  line-height: 1.7;
  overflow-y: auto;
}

.slide-bullets li {
  list-style: none;
  padding-left: 18px;
  position: relative;
}

.slide-bullets li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  width: 7px;
  height: 7px;
  border-radius: 2px;
  background: var(--td-brand-color);
}

.slide-code {
  position: relative;
  margin-top: 18px;
  background: var(--td-bg-secondary-container);
  border-radius: var(--td-radius-default);
  padding: 12px 16px;
  overflow: auto;
}

.slide-code pre {
  font-family: var(--td-font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.slide-code__lang {
  position: absolute;
  top: 6px;
  right: 10px;
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.slide-visual {
  margin-top: 18px;
  background: var(--td-brand-color-light);
  border-radius: var(--td-radius-medium);
  padding: 16px 18px;
  font-size: 13px;
  color: var(--td-text-secondary);
  display: flex;
  gap: 10px;
}

.slide-visual__type {
  color: var(--td-brand-color);
  font-family: var(--td-font-mono);
  font-size: 12px;
}

.slide-quiz {
  margin-top: 18px;
  font-size: 14px;
}

.quiz-stem {
  font-weight: 500;
}

.quiz-options {
  margin-top: 8px;
  padding-left: 20px;
  color: var(--td-text-secondary);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.slide-question {
  margin-top: 14px;
  font-size: 14px;
  color: var(--td-brand-color);
}

.slide-foot {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--td-text-placeholder);
  padding-top: 12px;
  margin-top: auto;
  border-top: 1px solid var(--td-component-stroke);
}

.slide-notes {
  margin-top: 14px;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
  padding: 14px 18px;
}

.slide-notes h5 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

.slide-notes .beat {
  font-size: 13px;
  line-height: 1.8;
  color: var(--td-text-secondary);
}

.slide-notes .beat-no {
  display: inline-block;
  min-width: 18px;
  color: var(--td-text-placeholder);
  font-family: var(--td-font-mono);
  font-size: 11px;
}

.preview__hint {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.preview__hint svg {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}
</style>
