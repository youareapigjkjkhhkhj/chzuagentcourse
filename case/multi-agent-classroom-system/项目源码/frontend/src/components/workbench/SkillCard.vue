<script setup lang="ts">
/**
 * 操作卡（P4-A10 / F4-10 的「禁止静默修改课程」）。
 *
 * Agent 每动一次课程，消息里就嵌一张卡：**正在跑**（转圈）→ **结果摘要**
 * （改了哪几页、花了多久）→ 想看细节就展开（参数、原始结果、失败原因）。
 *
 * 三件事写在卡上而不是泡在回复里：
 *
 * 1. **改了哪几页**单独拎出来做成可以点的标签 —— 「Agent 动了第 5 页」和
 *    「你可以立刻去看第 5 页」是同一件事的两半。
 * 2. **耗时**照实写。一次换语气要一分钟，用户在等的时候需要知道这是正常的。
 * 3. **失败也说**。技能失败不抛异常（`skills.run` 返回 `status=failed`），
 *    如果界面上不画出来，用户会以为那句话没被听见。
 *
 * 同一张卡两种来路：跑的时候是 SSE 的帧（带 `args` / `why`），跑完之后是
 * 消息里的 `skillCalls`（只有结果）。所以 `args` / `why` 都是可选的 ——
 * 历史消息里那几张卡只是没有「为什么」这一行而已。
 */
import { computed, ref } from 'vue'

import type { SkillStatus } from '@/types/api'

const props = withDefaults(
  defineProps<{
    skill: string
    /** 中文名（`GET /skills` 给的，拉不到时用内置兜底表）。 */
    title: string
    args?: Record<string, unknown>
    why?: string
    status: SkillStatus
    result?: Record<string, unknown> | null
    error?: string
    durationMs?: number
  }>(),
  { args: () => ({}), why: '', result: null, error: '', durationMs: 0 },
)

const emit = defineEmits<{
  openPage: [pageNo: number]
  /** 点出处：开材料抽屉看那一段原文（P4-A6 的另一半）。 */
  openSource: [source: Record<string, unknown>]
}>()

const open = ref(false)

/** 参数摘要：一个个列出来，值里的数组按顿号接上。 */
const paramLine = computed(() => {
  const parts: string[] = []
  for (const [key, value] of Object.entries(props.args)) {
    if (value === null || value === undefined || value === '') continue
    const text = Array.isArray(value) ? value.join('、') : String(value)
    if (text) parts.push(`${key}=${text}`)
  }
  return parts.join(' · ')
})

/** 这次动过哪几页。数字从结果里按各技能的写法取，取不到就是空数组。 */
const touched = computed<number[]>(() => {
  const data = props.result ?? {}
  const numbers = new Set<number>()
  const push = (raw: unknown) => {
    const value = Number(raw ?? 0)
    if (value > 0) numbers.add(value)
  }
  push(data.pageNo)
  for (const item of (data.changedPages as unknown[]) ?? []) push(item)
  for (const item of (data.pages as unknown[]) ?? []) {
    if (item && typeof item === 'object') push((item as Record<string, unknown>).pageNo)
    else push(item)
  }
  return [...numbers].sort((a, b) => a - b)
})

/** 一行结果摘要。写不下或者没话说的，交给下面那份原始结果。 */
const summary = computed(() => {
  const data = props.result ?? {}
  switch (props.skill) {
    case 'revise_outline': {
      const changed = (data.changed as string[]) ?? []
      const pages = (data.changedPages as number[]) ?? []
      return `第 ${data.chapterNo} 章改了${changed.length ? changed.join('、') : '内容'}${
        pages.length ? `，涉及 ${pages.length} 页` : ''
      }`
    }
    case 'rewrite_page':
      return `第 ${data.pageNo} 页已重写（rev ${data.rev}）`
    case 'change_tone':
      return `语气改成「${data.tone}」，动了 ${touched.value.length} 页`
    case 'add_quiz':
      return `第 ${data.pageNo} 页出了一道题：${data.stem ?? ''}`
    case 'add_page':
      return data.written
        ? `第 ${data.pageNo} 页已加上并写好内容`
        : `第 ${data.pageNo} 页加上了，但内容没写出来`
    case 'remove_page':
      return `已删掉第 ${data.pageNo} 页，课程剩 ${data.pageCount ?? '?'} 页`
    case 'summarize_material': {
      if (data.reason) return String(data.reason)
      return `从材料里找出 ${((data.sources as unknown[]) ?? []).length} 段相关原文`
    }
    default:
      return ''
  }
})

/** 材料摘要那条：答案是要点列表，摊在卡片里比藏在 JSON 里有用。 */
const points = computed<string[]>(() =>
  props.skill === 'summarize_material' ? ((props.result?.summary as string[]) ?? []) : [],
)

/** 摘要里的出处（`summarize_material` 会带回）：点了去抽屉里看原文。 */
const citations = computed(() => {
  const rows = (props.result?.sources as Record<string, unknown>[]) ?? []
  return props.skill === 'summarize_material' ? rows : []
})

const seconds = computed(() =>
  props.durationMs >= 1000 ? `${(props.durationMs / 1000).toFixed(1)}s` : `${props.durationMs}ms`,
)

const detail = computed(() => JSON.stringify(props.result ?? {}, null, 2))
</script>

<template>
  <div class="skill-card" :class="`is-${status}`">
    <div class="skill-card__head" @click="open = !open">
      <span class="st-ico">
        <svg v-if="status === 'ok'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
          <path d="M20 6 9 17l-5-5" />
        </svg>
        <svg v-else-if="status === 'failed'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4">
          <path d="M6 6l12 12M18 6 6 18" />
        </svg>
      </span>
      <span class="skill-card__title">{{ title }}</span>
      <span class="text-placeholder skill-card__name mono">{{ skill }}</span>
      <span class="spacer" />
      <span v-if="status !== 'running'" class="skill-card__time mono">{{ seconds }}</span>
      <svg class="skill-card__arrow" :class="{ 'is-open': open }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M9 6l6 6-6 6" />
      </svg>
    </div>

    <p v-if="why" class="skill-card__why">{{ why }}</p>
    <p v-if="paramLine" class="skill-card__params mono">{{ paramLine }}</p>

    <p v-if="status === 'running'" class="skill-card__line">正在执行…</p>
    <p v-else-if="status === 'failed'" class="skill-card__line is-error">{{ error || '这一步没做成' }}</p>
    <p v-else-if="summary" class="skill-card__line">{{ summary }}</p>

    <ul v-if="points.length" class="skill-card__points">
      <li v-for="(point, index) in points" :key="index">{{ point }}</li>
    </ul>

    <div v-if="touched.length" class="skill-card__pages">
      <span class="text-placeholder">影响页面</span>
      <button
        v-for="pageNo in touched"
        :key="pageNo"
        class="skill-card__page"
        @click="emit('openPage', pageNo)"
      >
        第 {{ pageNo }} 页
      </button>
    </div>

    <div v-if="citations.length" class="skill-card__pages">
      <span class="text-placeholder">出处</span>
      <button
        v-for="(row, index) in citations"
        :key="index"
        class="skill-card__page"
        :title="String(row.sectionPath || '打开这份材料的原文')"
        @click="emit('openSource', row)"
      >
        {{ row.fileName }}<template v-if="row.pageNo"> · 第 {{ row.pageNo }} 页</template>
      </button>
    </div>

    <div v-if="open" class="skill-card__detail">
      <pre>{{ detail }}</pre>
    </div>
  </div>
</template>

<style scoped>
/* 版式取自 产品原型/workbench.html 的 .task-card（同一套步骤卡的克制感）。 */
.skill-card {
  background: var(--td-bg-container);
  border: 1px solid var(--td-component-border);
  border-radius: var(--td-radius-medium);
  padding: 10px 12px;
  box-shadow: var(--td-shadow-1);
  max-width: 100%;
}

.skill-card.is-failed {
  border-color: var(--td-error-color-3);
}

.skill-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.skill-card__head .st-ico {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.skill-card__head .st-ico svg {
  width: 11px;
  height: 11px;
}

.is-ok .st-ico {
  background: var(--td-success-color-light);
  color: var(--td-success-color);
}

.is-failed .st-ico {
  background: var(--td-error-color-light);
  color: var(--td-error-color);
}

.is-running .st-ico {
  border: 2px solid var(--td-brand-color-focus);
  border-top-color: var(--td-brand-color);
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.skill-card__title {
  font-size: 13px;
  font-weight: 600;
}

.is-running .skill-card__title {
  color: var(--td-brand-color);
}

.skill-card__name {
  font-size: 11px;
}

.skill-card__head .spacer {
  flex: 1;
}

.skill-card__time {
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.skill-card__arrow {
  width: 13px;
  height: 13px;
  color: var(--td-text-placeholder);
  transition: transform 0.2s;
}

.skill-card__arrow.is-open {
  transform: rotate(90deg);
}

.skill-card__why,
.skill-card__params,
.skill-card__line {
  margin-top: 6px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--td-text-secondary);
}

.skill-card__why {
  color: var(--td-text-placeholder);
}

.skill-card__params {
  font-size: 11.5px;
  color: var(--td-text-placeholder);
  word-break: break-all;
}

.skill-card__line.is-error {
  color: var(--td-error-color);
}

.skill-card__points {
  margin-top: 6px;
  padding-left: 16px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--td-text-secondary);
  list-style: disc;
}

.skill-card__pages {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 11.5px;
}

.skill-card__page {
  border: 1px solid var(--td-component-border);
  background: transparent;
  border-radius: var(--td-radius-round);
  padding: 1px 8px;
  font-size: 11.5px;
  color: var(--td-text-secondary);
  cursor: pointer;
}

.skill-card__page:hover {
  border-color: var(--td-brand-color);
  color: var(--td-brand-color);
}

.skill-card__detail {
  margin-top: 8px;
  background: var(--td-bg-secondary-container);
  border-radius: var(--td-radius-default);
  padding: 8px 10px;
  max-height: 220px;
  overflow: auto;
}

.skill-card__detail pre {
  font-family: var(--td-font-mono);
  font-size: 11.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.mono {
  font-family: var(--td-font-mono);
}
</style>
