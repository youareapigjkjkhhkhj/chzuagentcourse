<script setup lang="ts">
/**
 * 首页的生成器卡片（版式照 `产品原型/index.html` 的 `.generator`）。
 *
 * 它只管「收集主题与模式」，发请求与跳转由页面负责 —— 组件里不出现路由，
 * 换一个入口（比如课堂页的活动面板）时这套输入框能直接复用。
 */
import { ref } from 'vue'

import { useSettingsStore } from '@/stores/settings'
import type { CourseMode } from '@/types/api'

defineProps<{
  estimatePages: number
  estimateMinutes: number
  submitting: boolean
}>()

const emit = defineEmits<{
  submit: [payload: { topic: string; mode: CourseMode; template: string }]
  upload: []
}>()

const settings = useSettingsStore()

const topic = ref('')
const mode = ref<CourseMode>('lecture')
/** 课程级 PPT 模板（配色+字体+版式）。清单由后端下发，认不出就退回 default。 */
const template = ref('default')
const hint = ref('')

const PLACEHOLDER = '输入你想学习的主题，例如：机器学习入门 · 从感知机到神经网络'

const EXAMPLES = [
  { text: '大语言模型原理通识', icon: 'sparkle' },
  { text: '给中学生的相对论入门', icon: 'smile' },
  { text: '宏观经济学：货币与利率', icon: 'book' },
  { text: 'Python 数据分析实战', icon: 'code' },
] as const

function useExample(text: string): void {
  topic.value = text
  hint.value = ''
}

/** 主题是空的就不发请求：服务端也会拒（P1-F1 的清洗），但让用户先看到原因更好。 */
function onStart(): void {
  const value = topic.value.trim()
  if (!value) {
    hint.value = '请先输入课程主题'
    return
  }
  hint.value = ''
  emit('submit', { topic: value, mode: mode.value, template: template.value })
}
</script>

<template>
  <div class="generator">
    <textarea
      v-model="topic"
      rows="3"
      :placeholder="PLACEHOLDER"
      @keydown.enter.exact.prevent="onStart"
    />
    <div class="generator__bar">
      <span class="gen-tool" @click="emit('upload')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <path
            d="M21 12.5 12.5 21a5.3 5.3 0 0 1-7.5-7.5l8.5-8.5a3.54 3.54 0 0 1 5 5l-8.5 8.5a1.77 1.77 0 0 1-2.5-2.5L15 8.5"
          />
        </svg>
        上传资料
      </span>
      <span
        class="gen-tool"
        :class="{ 'is-on': mode === 'lecture' }"
        @click="mode = 'lecture'"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <rect x="3" y="4" width="18" height="13" rx="2" />
          <path d="M8 21h8M12 17v4" />
        </svg>
        标准课堂
      </span>
      <span
        class="gen-tool"
        :class="{ 'is-on': mode === 'seminar' }"
        @click="mode = 'seminar'"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M8 12h8M8 8h5" />
          <path d="M21 12a9 9 0 1 1-4-7.5" />
        </svg>
        研讨模式
      </span>
      <span class="spacer" />
      <label v-if="settings.templates.length" class="gen-tpl">
        <span class="gen-tpl__label">模板</span>
        <t-select v-model="template" size="small" class="gen-tpl__select">
          <t-option
            v-for="one in settings.templates"
            :key="one.key"
            :value="one.key"
            :label="one.name"
          />
        </t-select>
      </label>
      <t-button
        theme="primary"
        size="large"
        class="gen-start"
        :loading="submitting"
        @click="onStart"
      >
        开始生成
        <svg class="btn-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      </t-button>
    </div>
    <p class="generator__est">
      预计生成 {{ estimatePages }} 页 · 约 {{ estimateMinutes }} 分钟课时
    </p>
    <p v-if="hint" class="generator__hint">{{ hint }}</p>
  </div>

  <div class="examples">
    <span class="text-placeholder try-label">试试：</span>
    <span
      v-for="example in EXAMPLES"
      :key="example.text"
      class="example-chip"
      @click="useExample(example.text)"
    >
      <svg
        v-if="example.icon === 'sparkle'"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
      >
        <path
          d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.2 2.2M16.2 16.2l2.2 2.2M18.4 5.6l-2.2 2.2M7.8 16.2l-2.2 2.2"
        />
        <circle cx="12" cy="12" r="3.5" />
      </svg>
      <svg
        v-else-if="example.icon === 'smile'"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M8 14c1.5-1.5 6.5-1.5 8 0M9 9.5h.01M15 9.5h.01" />
      </svg>
      <svg
        v-else-if="example.icon === 'book'"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
      >
        <path d="M4 19V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v14" />
        <path d="M4 19a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2M9 7h6M9 11h6" />
      </svg>
      <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
        <path d="M8 9l-4 3 4 3M16 9l4 3-4 3M13 5l-2 14" />
      </svg>
      {{ example.text }}
    </span>
  </div>
</template>

<style scoped>
/* 以下版式取自 产品原型/index.html 的 .generator / .examples */
.generator {
  max-width: 760px;
  margin: 40px auto 0;
  text-align: left;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-large);
  border: 1px solid var(--td-component-stroke);
  box-shadow: var(--td-shadow-2);
  transition:
    box-shadow 0.25s,
    border-color 0.25s;
}

.generator:focus-within {
  border-color: var(--td-brand-color);
  box-shadow: 0 0 0 3px var(--td-brand-color-focus), var(--td-shadow-2);
}

.generator textarea {
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  padding: 20px 24px 8px;
  font-family: var(--td-font-family);
  font-size: 16px;
  line-height: 1.7;
  color: var(--td-text-primary);
  background: transparent;
}

.generator textarea::placeholder {
  color: var(--td-text-placeholder);
}

.generator__bar {
  display: flex;
  align-items: center;
  /* 宽度不够时整块换行，而不是把「上传资料/标准课堂」这些标签从中间截断 */
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px dashed var(--td-component-border);
}

.generator__bar .spacer {
  flex: 1;
}

.generator__hint {
  padding: 0 16px 12px;
  font-size: 12px;
  color: var(--td-error-color);
}

/* 预计页数/时长挪到工具栏下方单独一行，不给单行工具栏添宽度 */
.generator__est {
  padding: 0 16px 12px;
  text-align: right;
  font-size: 12px;
  color: var(--td-text-secondary);
}

/* 开始生成按钮：不缩不换行，比默认 large 再高一圈、宽一点 */
.generator__bar .gen-start {
  flex-shrink: 0;
  white-space: nowrap;
  height: 44px;
  min-width: 148px;
  padding: 0 28px;
  font-size: 16px;
}

.btn-arrow {
  width: 16px;
  height: 16px;
  margin-left: 6px;
}

.gen-tool {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: var(--td-radius-default);
  font-size: 13px;
  color: var(--td-text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  /* 标签不允许被截断换行 */
  flex-shrink: 0;
  white-space: nowrap;
}

.gen-tool:hover {
  background: var(--td-bg-container-hover);
  color: var(--td-text-primary);
}

.gen-tool.is-on {
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
}

.gen-tool svg {
  width: 16px;
  height: 16px;
}

.gen-tpl {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.gen-tpl__label {
  font-size: 13px;
  color: var(--td-text-secondary);
  white-space: nowrap;
}

.gen-tpl__select {
  width: 132px;
}

.examples {
  max-width: 760px;
  margin: 20px auto 0;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
}

.try-label {
  font-size: 13px;
  line-height: 32px;
}

.example-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  background: var(--td-bg-container);
  border: 1px solid var(--td-component-border);
  border-radius: var(--td-radius-round);
  font-size: 13px;
  color: var(--td-text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.example-chip:hover {
  border-color: var(--td-brand-color);
  color: var(--td-brand-color);
  transform: translateY(-1px);
  box-shadow: var(--td-shadow-1);
}

.example-chip svg {
  width: 14px;
  height: 14px;
}
</style>
