<script setup lang="ts">
/**
 * 页面属性面板（版式照 `产品原型/workbench.html` 的 `.props`）。
 *
 * 两条规矩：
 *
 * 1. **保存只提交改动过的字段**（P1-A11）。空提交会把 `rev` 白白推上去，
 *    版本链就不再是「改过几次」的记录。所以这里自己存一份草稿，逐个字段
 *    和**服务端那份**比。
 * 2. **重写是同步的**（P1-A7）：点完就在等结果，不套一层任务与轮询 ——
 *    用户盯着的是一个面板，不是一张任务卡。
 */
import { computed, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

import * as api from '@/api'
import { describeError } from '@/stores/settings'
import type { CoursePageItem, SlideDsl } from '@/types/api'

const props = defineProps<{
  courseId: string
  page: CoursePageItem
}>()

const emit = defineEmits<{
  saved: [page: CoursePageItem]
  rewritten: [page: CoursePageItem]
}>()

/**
 * 三个快捷指令。值与后端 `prompts.QUICK_INSTRUCTIONS` 的 `value` 对齐 ——
 * 那边同时是「你什么都不填」时的默认指令来源，所以这里传的是短词，不是长句。
 */
const QUICK_INSTRUCTIONS = ['更通俗', '更深入', '换个例子'] as const

/**
 * 草稿里的一行文本。要点与讲稿都只是一串 `{ text }` —— 服务端会补上
 * `beatId` / `estSec` / `emphasis`，前端不假装自己知道这些值。
 *
 * 用对象而不是裸字符串，是为了让输入框能直接绑到 `beat.text`：v-for 里
 * 那个变量真用得上，行与值的对应也不会靠下标去猜。
 */
interface DraftText {
  text: string
}

interface Draft {
  title: string
  subtitle: string
  bullets: DraftText[]
  narration: DraftText[]
}

const draft = ref<Draft>({ title: '', subtitle: '', bullets: [], narration: [] })
/**
 * 面板收不收起来。默认开着 —— 它是这一页的编辑面，进来就该看见。
 * 收起是为了「这一页的版式我想看全」：中间那格预览有 960px 上限，
 * 收掉这 300px 是给它留白，不是它能不能显示完的前提。
 */
const collapsed = ref(false)

const rewriteOpen = ref(false)
const instruction = ref('')
const saving = ref(false)
const rewriting = ref(false)

function textsOf(dsl: SlideDsl, key: 'bullets' | 'narration'): DraftText[] {
  const rows = dsl[key] ?? []
  return rows.map((row) => ({ text: row.text ?? '' }))
}

function plainTexts(rows: DraftText[]): string[] {
  return rows.map((row) => row.text)
}

function fill(page: CoursePageItem): void {
  const dsl = page.dsl ?? {}
  draft.value = {
    title: dsl.title ?? '',
    subtitle: dsl.subtitle ?? '',
    bullets: textsOf(dsl, 'bullets'),
    narration: textsOf(dsl, 'narration'),
  }
}

watch(
  () => props.page,
  (page) => {
    fill(page)
    rewriteOpen.value = false
    instruction.value = ''
  },
  { immediate: true },
)

function sameTexts(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((text, index) => text === b[index])
}

/** 只装改动过的字段。没有改动就是一个空对象 —— 调用方据此不发请求。 */
const patch = computed<Record<string, unknown>>(() => {
  const dsl = props.page.dsl ?? {}
  const body: Record<string, unknown> = {}
  if (draft.value.title !== (dsl.title ?? '')) body.title = draft.value.title
  if (draft.value.subtitle !== (dsl.subtitle ?? '')) body.subtitle = draft.value.subtitle
  // 要点与讲稿都只交文本：emphasis / beatId / estSec 由服务端重算
  const bullets = plainTexts(draft.value.bullets)
  if (!sameTexts(bullets, plainTexts(textsOf(dsl, 'bullets')))) {
    body.bullets = bullets.map((text) => ({ text }))
  }
  const narration = plainTexts(draft.value.narration)
  if (!sameTexts(narration, plainTexts(textsOf(dsl, 'narration')))) {
    body.narration = narration.map((text) => ({ text }))
  }
  return body
})

const hasChanges = computed(() => Object.keys(patch.value).length > 0)

/** 要点用一个多行输入框编：一行一条，比一串小输入框好改。 */
const bulletsText = computed({
  get: () => plainTexts(draft.value.bullets).join('\n'),
  set: (value: string) => {
    draft.value.bullets = value.split('\n').map((text) => ({ text }))
  },
})

async function onSave(): Promise<void> {
  if (!hasChanges.value) {
    MessagePlugin.info('没有改动，这一页不用保存')
    return
  }
  saving.value = true
  try {
    const page = await api.savePage(props.courseId, props.page.pageNo, patch.value)
    emit('saved', page)
    MessagePlugin.success(`已保存为 rev ${page.rev}`)
  } catch (error) {
    MessagePlugin.error(describeError(error))
  } finally {
    saving.value = false
  }
}

async function onRewrite(): Promise<void> {
  rewriting.value = true
  try {
    const result = await api.rewritePage(
      props.courseId,
      props.page.pageNo,
      instruction.value || QUICK_INSTRUCTIONS[0],
    )
    emit('rewritten', result.page)
    MessagePlugin.success('AI 已重写这一页')
  } catch (error) {
    MessagePlugin.error(describeError(error))
  } finally {
    rewriting.value = false
  }
}
</script>

<template>
  <aside class="props" :class="{ 'is-collapsed': collapsed }">
    <!-- 整行可点：收起之后预览那边就宽出来一块，再点一下收回 -->
    <h4
      class="props__head"
      :title="collapsed ? '展开页面属性' : '收起页面属性'"
      @click="collapsed = !collapsed"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M4 6h16M4 12h16M4 18h10" />
      </svg>
      <span class="props__title">页面属性</span>
      <span class="spacer" />
      <span class="props__chevron" :class="{ 'is-folded': collapsed }">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M15 6l-6 6 6 6" />
        </svg>
      </span>
    </h4>

    <!--
      `v-show` 而不是 `v-if`：收起一下**不该把没保存的草稿丢掉**。草稿是跟着
      `props.page` 重填的（见 `watch`），组件一卸载就白填了。
    -->
    <div v-show="!collapsed" class="props__body">
      <div class="props__actions">
        <t-button class="wb-rewrite" size="small" variant="outline" @click="rewriteOpen = !rewriteOpen">
          AI 重写此页
        </t-button>
        <t-button class="wb-save" size="small" theme="primary" :loading="saving" @click="onSave">
          保存
        </t-button>
      </div>

      <div v-if="rewriteOpen" class="rewrite-panel">
        <p class="rewrite-panel__hint">选一个方向，或者自己写一句要求：</p>
        <div class="rewrite-panel__chips">
          <button
            v-for="item in QUICK_INSTRUCTIONS"
            :key="item"
            class="rewrite-chip"
            :class="{ 'is-on': instruction === item }"
            @click="instruction = item"
          >
            {{ item }}
          </button>
        </div>
        <t-input v-model="instruction" size="small" placeholder="例如：多举一个生活中的例子" />
        <t-button class="rewrite-go" size="small" theme="primary" :loading="rewriting" block @click="onRewrite">
          重写
        </t-button>
      </div>

      <div class="t-form-item">
        <label>页面标题</label>
        <t-input v-model="draft.title" size="small" />
      </div>

      <div class="t-form-item">
        <label>副标题</label>
        <t-input v-model="draft.subtitle" size="small" placeholder="可留空" />
      </div>

      <div v-if="draft.bullets.length" class="t-form-item">
        <label>要点（一行一条）</label>
        <t-textarea v-model="bulletsText" :autosize="{ minRows: 3, maxRows: 8 }" />
      </div>

      <div class="t-form-item">
        <label>讲稿（AI 教师口述）</label>
        <div class="page-narration">
          <t-textarea
            v-for="(beat, index) in draft.narration"
            :key="index"
            v-model="beat.text"
            :autosize="{ minRows: 2, maxRows: 6 }"
          />
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
/* 版式取自 产品原型/workbench.html 的 .props */
.props {
  width: 300px;
  flex-shrink: 0;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
  padding: 18px;
  /* 收起时宽度是动画过去的，中间那一刻里头的表单得被裁掉 */
  overflow: hidden;
  transition: width 0.2s ease;
}

/* 收起态：一根窄条，标题竖排（与材料抽屉的收起轨同一个视觉语言） */
.props.is-collapsed {
  width: 48px;
  padding: 12px 8px;
  cursor: pointer;
}

.props h4 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.props h4 svg {
  width: 15px;
  height: 15px;
  color: var(--td-brand-color);
  flex-shrink: 0;
}

.props__head {
  cursor: pointer;
  user-select: none;
}

.props__head .spacer {
  flex: 1;
}

.props__head:hover .props__title {
  color: var(--td-brand-color);
}

.props__chevron {
  display: flex;
  color: var(--td-text-placeholder);
  transition: transform 0.2s ease;
}

.props__chevron svg {
  width: 14px;
  height: 14px;
}

/* 收起来之后这个箭头是「再点一下就回来」，所以掉个头 */
.props__chevron.is-folded {
  transform: rotate(180deg);
}

.props.is-collapsed h4 {
  flex-direction: column;
  gap: 10px;
  margin-bottom: 0;
}

.props.is-collapsed .props__title {
  writing-mode: vertical-rl;
  letter-spacing: 2px;
}

.props__actions {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}

.props__actions :deep(.t-button) {
  flex: 1;
}

.t-form-item {
  margin-bottom: 14px;
}

.t-form-item label {
  display: block;
  font-size: 12px;
  color: var(--td-text-secondary);
  margin-bottom: 6px;
}

.page-narration {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rewrite-panel {
  border: 1px dashed var(--td-component-border);
  border-radius: var(--td-radius-default);
  padding: 10px 12px;
  margin-bottom: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rewrite-panel__hint {
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.rewrite-panel__chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.rewrite-chip {
  border: 1px solid var(--td-component-border);
  background: transparent;
  border-radius: var(--td-radius-round);
  padding: 3px 10px;
  font-size: 12px;
  color: var(--td-text-secondary);
  cursor: pointer;
}

.rewrite-chip:hover {
  border-color: var(--td-brand-color);
  color: var(--td-brand-color);
}

.rewrite-chip.is-on {
  border-color: var(--td-brand-color);
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
}
</style>
