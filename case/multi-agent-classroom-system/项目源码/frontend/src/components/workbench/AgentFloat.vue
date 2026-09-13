<script setup lang="ts">
/**
 * 右下角的生成任务 / 对话 / 材料浮框。
 *
 * 这几件事原来各占一块地方：任务卡挤在消息流顶上、对话在下面、大纲树再折叠着
 * 插一脚，材料单独一个 340px 的右栏。现在把它们收进一个**能收起来的**浮框，
 * 左栏整个让给课程大纲，右栏取消、宽度还给预览 —— 大纲是要一直看着的，
 * 任务进度、对话、材料都是「有事才看」的，这几类东西不该一起抢版面。
 *
 * 页签而不是并排，是因为它们本来就是同一件事的几面：正在写第几页（任务）、
 * 「我刚说了什么」（对话）、「这门课底下垫着什么」（材料）看的是同一次生成。
 * 默认跟着任务走 —— 有任务就停在「生成任务」，没有（打开一门老课）就直接是
 * 「对话」。
 *
 * 材料这一页是右栏那个抽屉整体搬进来的，所以尺寸得改：抽屉原来按「右栏」活
 * （340px 定宽、一条左边框、自己一根收起轨），进了浮框就铺满、不要边框 ——
 * 见 `is-materials` 那两条样式。总开关（`materialEnabled`）也随它一起进到这里，
 * 关着时整页签不出现。
 *
 * 收起态是一个小胶囊。它不是装饰：生成跑起来之后用户多半要去看中间的预览，
 * 这时候一个占半屏的框就是碍事；但进度还得能瞟一眼，所以胶囊上也写百分比。
 */
import { computed, ref, watch } from 'vue'

import ChatThread from '@/components/workbench/ChatThread.vue'
import GenTaskPanel from '@/components/workbench/GenTaskPanel.vue'
import MaterialDrawer from '@/components/workbench/MaterialDrawer.vue'
import type { PageRewrite } from '@/composables/useWorkbenchChat'
import type { JobStatus, LiveStep, SlideSource, WriteBatch } from '@/types/api'

const props = defineProps<{
  courseId: string
  /** 材料总开关（P4-G3）。关着时「材料」页签整个不出现，抽屉也不挂载。 */
  materialsEnabled: boolean
  /** 用户正看着哪一页 —— 说话时捎给 Agent（「这一页」指的就是它）。 */
  refPageNo: number
  jobId: string
  steps: LiveStep[]
  batches: WriteBatch[]
  percent: number | null
  status: JobStatus | ''
  canceled: boolean
  error: string
  /** 断点续跑：「继续生成」按钮亮不亮，由服务端判（P5-F5-9）。 */
  resumable: boolean
  /** 进度是推来的还是回问来的，如实写一行。 */
  linkLine: string
}>()

const emit = defineEmits<{
  cancel: []
  retry: [stepId: string]
  resume: []
  pageRewritten: [info: PageRewrite]
  selectPage: [pageNo: number]
  openSource: [source: SlideSource]
  /** 材料里某段原文取不到了（材料被删）。工作台据此把出处徽标画成失效态。 */
  missing: [key: string]
}>()

type Tab = 'task' | 'chat' | 'materials'

const expanded = ref(true)
const tab = ref<Tab>(props.jobId ? 'task' : 'chat')

/** 抽屉自己的收起态。它原来靠「右栏的展开/收起」表达，现在那件事由页签做。 */
const drawerCollapsed = ref(false)
const drawerEl = ref<InstanceType<typeof MaterialDrawer> | null>(null)

/** 冒出一个新任务就自动展开、并跳到「生成任务」——那正是用户此刻要看的东西。 */
watch(
  () => props.jobId,
  (id) => {
    if (!id) return
    expanded.value = true
    tab.value = 'task'
  },
)

/**
 * 材料总开关被关掉时不能把人留在空页签上。
 * 关掉的是服务端能力（`/capabilities`），页签跟着消失，所以得挪一步。
 */
watch(
  () => props.materialsEnabled,
  (on) => {
    if (!on && tab.value === 'materials') tab.value = props.jobId ? 'task' : 'chat'
  },
)

/**
 * 切到材料页签并展开浮框。**工作台外面那两件事要它**：
 * 拖文件到页面任意处（收着的时候得先把地方露出来）、点出处徽标去溯源。
 */
function showMaterials(): void {
  expanded.value = true
  tab.value = 'materials'
  drawerCollapsed.value = false
}

defineExpose({
  showMaterials,
  /**
   * 翻到某一段原文。`focusSource` 自己会把抽屉从收起态翻回来（见那个模块），
   * 所以这里不必再管一次。
   */
  focusMaterial: (payload: {
    fileId: string
    chunkId: string
    page?: number | null
    quote?: string
  }) => drawerEl.value?.focusSource(payload),
  /** 拖到工作台任意位置的文件也走这里，交给抽屉逐个上传。 */
  uploadFiles: (files: File[]) => files.forEach((file) => void drawerEl.value?.upload(file)),
})

const STATUS_TEXT: Record<JobStatus, string> = {
  queued: '排队中',
  running: '正在生成',
  paused: '已暂停',
  done: '生成完成',
  failed: '生成失败',
  canceled: '已取消',
}

/** 头部那行小字。详细的进度在任务卡里，这里只报一句。 */
const statusText = computed(() => {
  if (!props.jobId) return '还没有生成任务'
  const base = STATUS_TEXT[props.status as JobStatus] ?? '生成中'
  if (props.status === 'running' && props.percent !== null) return `${base} · ${props.percent}%`
  return base
})

/** 收起时胶囊上写什么：正在跑就带上百分比。 */
const pillText = computed(() => {
  if (!props.jobId) return '课程生成 Agent'
  const running = props.status === 'running' || props.status === 'queued'
  return running && props.percent !== null ? `课程生成 Agent · ${props.percent}%` : '课程生成 Agent'
})
</script>

<template>
  <div class="wb-float" :class="{ 'is-collapsed': !expanded }">
    <!-- 收起态：一个胶囊。点开回到上次那个页签 -->
    <button v-if="!expanded" class="wb-float__pill" @click="expanded = true">
      <span class="wb-float__dot" :class="`is-${status || 'idle'}`" />
      {{ pillText }}
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M6 15l6-6 6 6" />
      </svg>
    </button>

    <!--
      展开态。用 v-show 收起来而不是 v-if：对话状态（消息、草稿、滚动位置）
      都在子组件里，卸载一次就全丢了 —— 收起一下不该等于清空聊天框。
    -->
    <section v-show="expanded" class="wb-float__panel">
      <header class="wb-float__head">
        <t-avatar shape="circle" :style="{ background: 'linear-gradient(135deg,#0052d9,#618eff)' }">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8">
            <path
              d="M12 3l1.8 4.7L18.5 9l-4.7 1.8L12 15.5l-1.8-4.7L5.5 9l4.7-1.3L12 3ZM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z"
            />
          </svg>
        </t-avatar>
        <div class="wb-float__id">
          <h3>课程生成 Agent</h3>
          <p :title="statusText">{{ statusText }}</p>
        </div>
        <span class="spacer" />
        <button class="wb-float__icon" title="收起来" @click="expanded = false">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      </header>

      <div class="wb-float__tabs">
        <button :class="{ 'is-on': tab === 'task' }" @click="tab = 'task'">
          生成任务
          <span v-if="status === 'running'" class="wb-float__spin" />
        </button>
        <button :class="{ 'is-on': tab === 'chat' }" @click="tab = 'chat'">对话</button>
        <!-- 材料总开关关着时这一页签整个不出现（P4-G3） -->
        <button
          v-if="materialsEnabled"
          :class="{ 'is-on': tab === 'materials' }"
          @click="tab = 'materials'"
        >
          材料
        </button>
      </div>

      <!-- 三个页签都留在 DOM 里（v-show）：任务卡是测试与状态的一部分，
           对话更是切走一下就不该丢，材料抽屉切走再回来也不该重读一遍。 -->
      <div v-show="tab === 'task'" class="wb-float__body">
        <GenTaskPanel
          :job-id="jobId"
          :steps="steps"
          :batches="batches"
          :percent="percent"
          :status="status"
          :canceled="canceled"
          :error="error"
          :resumable="resumable"
          :link-line="linkLine"
          @cancel="emit('cancel')"
          @retry="emit('retry', $event)"
          @resume="emit('resume')"
        />
        <t-empty
          v-if="!jobId"
          size="small"
          title="还没有生成任务"
          description="从首页输入一个主题开始生成；直接在这里说要改什么也行。"
        />
      </div>

      <div v-show="tab === 'chat'" class="wb-float__body is-chat">
        <ChatThread
          :course-id="courseId"
          :ref-page-no="refPageNo"
          @page-rewritten="emit('pageRewritten', $event)"
          @select-page="emit('selectPage', $event)"
          @open-source="emit('openSource', $event)"
        />
      </div>

      <!-- 材料抽屉。`v-if` 承接总开关：关掉时连挂载都不该有（它会打材料接口）。
           空 courseId 时抽屉自己提前 return，所以没开课时挂在这儿也是安静的。 -->
      <div v-show="tab === 'materials'" class="wb-float__body is-materials">
        <MaterialDrawer
          v-if="materialsEnabled"
          ref="drawerEl"
          v-model:collapsed="drawerCollapsed"
          :course-id="courseId"
          @missing="emit('missing', $event)"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
/*
 * 固定右下角。`position: fixed` 而不是 absolute：工作台那一层是
 * `overflow: hidden` 的横向 flex，absolute 会被它裁掉。
 */
.wb-float {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 40;
  width: 380px;
  max-width: calc(100vw - 40px);
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.wb-float__pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 999px;
  background: var(--td-bg-container);
  box-shadow: var(--td-shadow-2);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  color: var(--td-text-primary);
  cursor: pointer;
}

.wb-float__pill:hover {
  border-color: var(--td-brand-color);
  color: var(--td-brand-color);
}

.wb-float__pill svg {
  width: 14px;
  height: 14px;
}

.wb-float__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--td-text-placeholder);
}

.wb-float__dot.is-running,
.wb-float__dot.is-queued {
  background: var(--td-brand-color);
}

.wb-float__dot.is-done {
  background: var(--td-success-color);
}

.wb-float__dot.is-failed {
  background: var(--td-error-color);
}

.wb-float__panel {
  width: 100%;
  height: min(560px, calc(100vh - 120px));
  display: flex;
  flex-direction: column;
  background: var(--td-bg-container);
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--td-radius-large, 8px);
  box-shadow: var(--td-shadow-3);
  overflow: hidden;
}

.wb-float__head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
}

.wb-float__head .spacer {
  flex: 1;
}

.wb-float__id {
  min-width: 0;
}

.wb-float__head h3 {
  font-size: 15px;
  font-weight: 600;
}

.wb-float__head p {
  font-size: 12px;
  color: var(--td-text-placeholder);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.wb-float__icon {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--td-text-placeholder);
  cursor: pointer;
}

.wb-float__icon:hover {
  background: var(--td-bg-container-hover);
  color: var(--td-brand-color);
}

.wb-float__icon svg {
  width: 16px;
  height: 16px;
}

.wb-float__tabs {
  display: flex;
  gap: 4px;
  padding: 0 14px;
  border-bottom: 1px solid var(--td-component-stroke);
}

.wb-float__tabs button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  font: inherit;
  font-size: 13px;
  color: var(--td-text-secondary);
  cursor: pointer;
}

.wb-float__tabs button.is-on {
  color: var(--td-brand-color);
  border-bottom-color: var(--td-brand-color);
  font-weight: 600;
}

/* 生成中：页签上一个小圆点在转，切到别的页签也知道它还在跑 */
.wb-float__spin {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--td-brand-color);
  animation: wb-float-pulse 1.2s ease-in-out infinite;
}

@keyframes wb-float-pulse {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}

.wb-float__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--td-bg-page);
}

/* 对话那一页自己管滚动（消息流在里面滚），外面这一层别再套一层滚动条 */
.wb-float__body.is-chat {
  overflow: hidden;
  padding: 0;
  background: var(--td-bg-container);
}

/* 材料这一页同理：抽屉自己有头、有列表、有详情，滚动归它 */
.wb-float__body.is-materials {
  overflow: hidden;
  padding: 0;
  background: var(--td-bg-container);
}

/*
 * 抽屉是按「右栏」写的：340px 定宽 + 一条左边框 + 自己一根收起轨。
 * 搬进浮框之后这几样都不成立了 —— 铺满这一格、边框去掉、高度跟上
 * （它原来靠外层 `align-items: stretch` 撑满，现在这一层是竖向 flex，
 * 不给 `flex: 1` 就只剩内容那么高）。
 */
.wb-float__body.is-materials :deep(.drawer) {
  width: 100%;
  flex: 1;
  min-height: 0;
  border-left: 0;
}
</style>
