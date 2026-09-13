<script setup lang="ts">
/**
 * 课堂测验卡（F3-8 / P3-A7）：遇到 `kind=quiz` 的页弹出来，等学生作答。
 *
 * **选项发的是整句话，不是 A/B/C/D**。后端 `quiz_submit` 拿 `option` 与题面里的
 * `answer` 比字符串，题面里 `options` 是四句话、`answer` 也是其中一句话
 * （见 `runtime.quiz_question`）。发 "A" 会判错，而且看不出为什么 ——
 * 那个错很像是「答对了却没算对」，最难查的一类。
 *
 * **答案在下发时是不存在的**：`quiz` 事件里已经 `pop` 掉了 `answer` 与
 * `explain`，它们只在判定之后由 `quiz_result` 给回来。所以这一段没有
 * 「本地判定」的可能，也不需要。
 */
import { computed } from 'vue'

import type { ClassroomQuiz, QuizResult } from '@/types/classroom'

const props = withDefaults(
  defineProps<{
    quiz?: ClassroomQuiz | null
    result?: QuizResult | null
    submitting?: boolean
    /** 老师正在说的话（题面出来时老师通常会念一遍）。 */
    reading?: string
  }>(),
  { quiz: null, result: null, submitting: false, reading: '' },
)

const emit = defineEmits<{ submit: [option: string] }>()

const answered = computed(() => props.result !== null)

/** 我选的那一句：判定之后用它给选项上色。 */
function stateOf(option: string): '' | 'is-right' | 'is-wrong' {
  const result = props.result
  if (!result) return ''
  if (option === result.answer) return 'is-right'
  if (option === result.option) return 'is-wrong'
  return ''
}

function pick(option: string): void {
  if (answered.value || props.submitting) return // 答过就是答过了，不重发（重新答一遍走「再答一次」）
  emit('submit', option)
}

/** 答错之后的下一步。`remedial` 是后端给的分支名，前端只翻译不说别的。 */
const branchText = computed(() => {
  if (!props.result) return ''
  return props.result.correct ? '回答正确，继续讲下一段。' : '答错了 —— 看一下解析，这个知识点稍后再过一遍。'
})
</script>

<template>
  <div v-if="quiz" class="quiz">
    <div class="quiz__head">
      <t-tag theme="primary" variant="light">随堂测验</t-tag>
      <span class="quiz__page">第 {{ quiz.pageNo }} 页</span>
      <t-tag v-if="quiz.conceptTag" variant="light">{{ quiz.conceptTag }}</t-tag>
    </div>

    <div class="quiz__stem">{{ quiz.stem }}</div>
    <div v-if="reading" class="quiz__reading">老师正在念：{{ reading }}</div>

    <div class="quiz__options">
      <button
        v-for="(option, index) in quiz.options"
        :key="option"
        class="opt"
        :class="stateOf(option)"
        :disabled="answered || submitting"
        @click="pick(option)"
      >
        <span class="opt__key">{{ 'ABCD'[index] ?? index + 1 }}</span>
        <span class="opt__text">{{ option }}</span>
        <svg
          v-if="stateOf(option) === 'is-right'"
          class="opt__mark"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.4"
        >
          <path d="M20 6 9 17l-5-5" />
        </svg>
        <svg
          v-else-if="stateOf(option) === 'is-wrong'"
          class="opt__mark"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.4"
        >
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </div>

    <div v-if="result" class="quiz__result" :class="result.correct ? 'is-right' : 'is-wrong'">
      <div class="quiz__verdict">{{ result.correct ? '回答正确' : '回答错误' }}</div>
      <div class="quiz__branch">{{ branchText }}</div>
      <div v-if="result.explain" class="quiz__explain">
        <span class="quiz__explain-label">解析</span>
        <span>{{ result.explain }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.quiz {
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--td-radius-medium);
  background: var(--td-bg-container);
  box-shadow: var(--td-shadow-1);
  padding: 14px 16px;
}

.quiz__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.quiz__page {
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.quiz__stem {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.7;
  color: var(--td-text-primary);
}

.quiz__reading {
  margin-top: 6px;
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.quiz__options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.opt {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  text-align: left;
  padding: 9px 12px;
  border-radius: var(--td-radius-default);
  border: 1px solid var(--td-component-stroke);
  background: var(--td-bg-container);
  color: var(--td-text-primary);
  font-size: 13px;
  line-height: 1.6;
  cursor: pointer;
  transition: all 0.15s;
}

.opt:hover:not(:disabled) {
  border-color: var(--td-brand-color);
  background: var(--td-brand-color-light);
}

.opt:disabled {
  cursor: default;
}

.opt__key {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--td-bg-page);
  color: var(--td-text-secondary);
  font-size: 11px;
  font-weight: 600;
}

.opt__text {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}

.opt__mark {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

/* 判定之后：对的那一项永远是绿的（哪怕不是我选的）—— 要让人看见正确答案 */
.opt.is-right {
  border-color: var(--td-success-color);
  background: var(--td-success-color-light);
}

.opt.is-right .opt__key,
.opt.is-right .opt__mark {
  background: var(--td-success-color);
  color: var(--td-text-anti);
}

.opt.is-wrong {
  border-color: var(--td-error-color);
  background: var(--td-error-color-light);
}

.opt.is-wrong .opt__key {
  background: var(--td-error-color);
  color: var(--td-text-anti);
}

.opt.is-wrong .opt__mark {
  color: var(--td-error-color);
}

.quiz__result {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--td-component-stroke);
}

.quiz__verdict {
  font-size: 14px;
  font-weight: 600;
}

.quiz__result.is-right .quiz__verdict {
  color: var(--td-success-color);
}

.quiz__result.is-wrong .quiz__verdict {
  color: var(--td-error-color);
}

.quiz__branch {
  margin-top: 4px;
  font-size: 13px;
  color: var(--td-text-secondary);
}

.quiz__explain {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--td-text-secondary);
}

.quiz__explain-label {
  flex-shrink: 0;
  color: var(--td-text-placeholder);
}
</style>
