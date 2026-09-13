<script setup lang="ts">
/**
 * 溯源徽标（P4-A6 / F4-8）。
 *
 * 一页里每一条出处都写到底：「📄 第 12 页」挂在要点区末尾，鼠标停上去先看
 * 一眼原文（`quote` 是后端核对过的**一字不差的连续片段**，所以这里敢直接显示），
 * 点一下让右边抽屉翻到那一段。
 *
 * `missing` 是「这份材料已经删了」——消息说得很直白，徽标也不装作还点得动。
 * 判断放在工作台那边（它才知道抽屉取原文取到了什么），组件只管画。
 */
import { computed } from 'vue'

import type { SlideSource } from '@/types/api'

const props = defineProps<{
  source: SlideSource
  /** 抽屉里正显示着的就是这一条。 */
  active?: boolean
  /** 材料已删、原文取不到了。 */
  missing?: boolean
  /** 与 `missing` 无关的引用不上：引文没核对上（`sourceMissing`）是整页的事。 */
}>()

const emit = defineEmits<{ open: [source: SlideSource] }>()

/** 徽标上那行字：有页码就写页码，纯文本材料（没有页码）退回章节名。 */
const label = computed(() => {
  const { pageNo, sectionPath } = props.source
  if (pageNo) return `第 ${pageNo} 页`
  const last = sectionPath.split('>').pop()?.trim()
  return last || '原文'
})

const popTitle = computed(() => {
  const name = props.source.fileName || '关联材料'
  return props.source.pageNo ? `${name} · 第 ${props.source.pageNo} 页` : name
})
</script>

<template>
  <span class="src" :class="{ 'is-active': active, 'is-missing': missing }">
    <button class="src__chip" :title="missing ? '这份材料的出处已经找不到了' : '看原文'" @click="emit('open', source)">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
        <path d="M14 3v5h5M15 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-4-5Z" />
      </svg>
      {{ missing ? `${label}（已失效）` : label }}
    </button>

    <span class="src__pop">
      <span class="src__pop-head">
        {{ popTitle }}
        <template v-if="source.sectionPath"> · {{ source.sectionPath }}</template>
      </span>
      <span class="src__pop-quote">{{ missing ? '对应的材料已经删除，原文取不到了。' : source.quote }}</span>
      <span class="src__pop-foot">
        <template v-if="missing">材料已删除</template>
        <template v-else>相关度 {{ source.score.toFixed(2) }} · 点击看原文</template>
      </span>
    </span>
  </span>
</template>

<style scoped>
.src {
  position: relative;
  display: inline-flex;
  vertical-align: middle;
}

.src__chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border: 1px solid var(--td-component-border);
  background: var(--td-bg-container);
  border-radius: var(--td-radius-round);
  padding: 1px 8px;
  font-size: 11.5px;
  color: var(--td-text-secondary);
  cursor: pointer;
  white-space: nowrap;
}

.src__chip svg {
  width: 11px;
  height: 11px;
}

.src__chip:hover,
.src.is-active .src__chip {
  border-color: var(--td-brand-color);
  color: var(--td-brand-color);
  background: var(--td-brand-color-light);
}

.src.is-missing .src__chip {
  border-style: dashed;
  color: var(--td-text-placeholder);
  text-decoration: line-through;
  cursor: not-allowed;
}

/* 浮层：鼠标停上去先看一眼原文，不必先跳过去 */
.src__pop {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  z-index: 30;
  width: 320px;
  display: none;
  flex-direction: column;
  gap: 6px;
  background: var(--td-bg-container);
  border: 1px solid var(--td-component-border);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-3);
  padding: 10px 12px;
}

.src:hover .src__pop {
  display: flex;
}

.src__pop-head {
  font-size: 11.5px;
  color: var(--td-brand-color);
}

.src__pop-quote {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--td-text-secondary);
  max-height: 140px;
  overflow: hidden;
}

.src__pop-foot {
  font-size: 11px;
  color: var(--td-text-placeholder);
}
</style>
