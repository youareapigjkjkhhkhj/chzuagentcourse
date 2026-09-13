<script setup lang="ts">
/**
 * 与生成 Agent 的会话（P4 §6）：消息流 + 输入框。
 *
 * 它是从 `ChatPanel` 里拆出来的 —— 那一栏原来同时装着大纲树、任务卡和这段
 * 会话，三样东西抢一块 380px 宽的地方。现在这一份挂在右下角的 `AgentFloat`
 * 里，外面那层管「开不开、在哪个页签」，这里只管**说话**。
 *
 * 两件事仍然只在这里发生：
 *
 * 1. `refPageNo` 把「我正在看第几页」随消息一起交上去 —— 于是「这一页再讲
 *    细一点」不需要用户报页号。
 * 2. 回滚（`rollback`）是**对某一条消息**的：Agent 改错了页要退回去，
 *    退到那条消息之前的那一版。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

import ChatMessage from '@/components/workbench/ChatMessage.vue'
import { useWorkbenchChat, type CardView, type PageRewrite } from '@/composables/useWorkbenchChat'
import type { ChatMessageItem, SlideSource } from '@/types/api'

const props = defineProps<{
  courseId: string
  /** 用户正看着哪一页 —— 作为这次说话的语境一起发上去。 */
  refPageNo: number
}>()

const emit = defineEmits<{
  /** 某一页被改了：工作台去刷新预览与大纲。 */
  pageRewritten: [info: PageRewrite]
  /** 点操作卡上的「第 N 页」：打开那一页。 */
  selectPage: [pageNo: number]
  /** 点材料摘要卡上的出处：开材料抽屉定位原文（与页面徽标同一种载荷）。 */
  openSource: [source: SlideSource]
}>()

const courseIdRef = computed(() => props.courseId)

const {
  messages,
  skills,
  titles,
  draftId,
  draftText,
  liveSkills,
  pendingUser,
  running,
  connected,
  error,
  loaded,
  canSend,
  send,
  rollback,
} = useWorkbenchChat(courseIdRef, {
  onPageRewritten: (info: PageRewrite) => emit('pageRewritten', info),
})

const draft = ref('')
const helpOpen = ref(false)
const listEl = ref<HTMLElement | null>(null)
/** 用户把它滚上去看历史了：这时候别再自动拽回底部。 */
const pinned = ref(true)

const MAX_CHARS = 2000

/** 消息 + 那一条还没落库的本地回显。 */
interface Row {
  key: string
  message: ChatMessageItem
  text: string
  cards: CardView[]
  streaming: boolean
  tail: number
}

const rows = computed<Row[]>(() => {
  const out: Row[] = []
  const count = messages.value.length
  messages.value.forEach((message, index) => {
    const streaming = message.id === draftId.value
    out.push({
      key: message.id,
      message,
      // 正在流式出现的那条：屏幕上跟着字走；库里那条要等这一轮结束才有正文
      text: streaming && draftText.value ? draftText.value : message.content,
      cards: liveSkills.value[message.id] ?? message.skillCalls,
      streaming: streaming && running.value,
      tail: count - index,
    })
  })
  const pending = pendingUser.value
  if (pending) {
    // 刚发出去、服务端那份还没读回来：先画一条本地的（`send` 里清了就撤）
    out.push({
      key: 'pending',
      message: {
        id: 'pending',
        sessionId: '',
        seq: count + 1,
        role: 'user',
        content: pending.text,
        skillCalls: [],
        refPageNo: pending.refPageNo || null,
        tokens: 0,
        createdAt: '',
      },
      text: pending.text,
      cards: [],
      streaming: false,
      tail: 1,
    })
  }
  return out
})

function openPage(pageNo: number): void {
  if (pageNo > 0) emit('selectPage', pageNo)
}

/**
 * 卡片上的出处 → 与页面徽标**同一个载荷**（`SlideSource`）。
 * 两处出处合流成一种形状，工作台那边就只有一个开抽屉的入口。
 */
function onOpenSource(row: Record<string, unknown>): void {
  const materialId = String(row.materialId ?? '')
  const chunkId = String(row.chunkId ?? '')
  if (!materialId || !chunkId) return
  emit('openSource', {
    materialId,
    chunkId,
    pageNo: (row.pageNo as number | null) ?? null,
    sectionPath: String(row.sectionPath ?? ''),
    quote: String(row.quote ?? ''),
    score: Number(row.score ?? 0),
    fileName: row.fileName ? String(row.fileName) : undefined,
  })
}

/* --- 输入 --- */

async function submit(): Promise<void> {
  const text = draft.value.trim()
  if (!text) return
  if (running.value) {
    MessagePlugin.info('上一轮还在跑，等它结束')
    return
  }
  const ok = await send(text, props.refPageNo)
  if (ok) {
    draft.value = ''
    pinned.value = true
  } else if (error.value) {
    MessagePlugin.error(error.value)
  }
}

/**
 * 回车发送、Shift+回车换行。
 *
 * TDesign 的 textarea 把键盘事件带着**输入框的值**一起发出来
 * （`(value, { e })`），所以要的键盘事件在第二个参数里 —— 直接当 DOM 事件
 * 用会拿到一个字符串。
 */
function onKeydown(_value: unknown, context: { e: KeyboardEvent }): void {
  const event = context.e
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  void submit()
}

async function onRollback(messageId: string): Promise<void> {
  const notice = await rollback(messageId)
  if (notice) MessagePlugin.info(notice)
  else if (error.value) MessagePlugin.error(error.value)
}

/* --- 滚动 --- */

function onScroll(): void {
  const el = listEl.value
  if (!el) return
  pinned.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

const signature = computed(() =>
  [rows.value.length, draftText.value.length, Object.keys(liveSkills.value).length].join(':'),
)

watch(signature, async () => {
  if (!pinned.value) return
  await nextTick()
  const el = listEl.value
  if (el) el.scrollTop = el.scrollHeight
})
</script>

<template>
  <div class="ct">
    <!-- 能做什么：清单来自 GET /skills（F4-12），不是写死在前端的文案 -->
    <div class="ct__bar">
      <t-tag v-if="running" theme="primary" variant="light" size="small">思考中</t-tag>
      <span class="spacer" />
      <button class="ct__help" @click="helpOpen = !helpOpen">这个助手能做什么</button>
    </div>

    <div v-if="helpOpen" class="ct-help">
      <div v-for="item in skills" :key="item.name" class="ct-help__row">
        <span class="ct-help__name">{{ item.title }}</span>
        <span class="ct-help__desc">{{ item.description }}</span>
      </div>
      <p v-if="!skills.length" class="text-placeholder">技能清单没拉下来，先直接说要求也行。</p>
    </div>

    <div ref="listEl" class="ct__msgs" @scroll="onScroll">
      <ChatMessage
        v-for="row in rows"
        :key="row.key"
        :message="row.message"
        :text="row.text"
        :cards="row.cards"
        :titles="titles"
        :streaming="row.streaming"
        :tail-count="row.tail"
        @rollback="onRollback"
        @open-page="openPage"
        @open-source="onOpenSource"
      />

      <div v-if="!rows.length && loaded" class="ct__empty">
        <t-empty
          size="small"
          title="还没有开始对话"
          description="直接说要改什么，例如「把第三章压缩成 2 页」「第 3 页再讲细一点」。"
        />
      </div>
      <div v-else-if="!loaded && !rows.length" class="ct__empty">
        <t-empty size="small" title="还没有选择课程" description="回首页输入一个主题就能开工。" />
      </div>
    </div>

    <p v-if="!connected && canSend" class="ct__link">实时推送未连接，回复可能会晚一步显示</p>

    <div class="ct__input">
      <t-textarea
        v-model="draft"
        :maxlength="MAX_CHARS"
        :autosize="{ minRows: 2, maxRows: 5 }"
        placeholder="继续提要求，例如：第三章多加一个代码示例"
        @keydown="onKeydown"
      />
      <t-button
        class="ct__send"
        theme="primary"
        :loading="running"
        :disabled="!canSend || !draft.trim()"
        @click="submit"
      >
        发送
      </t-button>
    </div>
  </div>
</template>

<style scoped>
.ct {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}

/* 页签下面那一条：状态在左，帮助入口在右 */
.ct__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--td-component-stroke);
}

.ct__bar .spacer {
  flex: 1;
}

.ct__help {
  border: none;
  background: transparent;
  color: var(--td-text-placeholder);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}

.ct__help:hover {
  color: var(--td-brand-color);
}

.ct-help {
  padding: 10px 14px;
  border-bottom: 1px solid var(--td-component-stroke);
  background: var(--td-bg-secondary-container);
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
}

.ct-help__row {
  display: flex;
  gap: 8px;
  font-size: 12px;
  line-height: 1.6;
}

.ct-help__name {
  font-weight: 600;
  flex-shrink: 0;
  color: var(--td-brand-color);
}

.ct-help__desc {
  color: var(--td-text-secondary);
}

.ct__msgs {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--td-bg-page);
  min-height: 0;
}

.ct__empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ct__link {
  font-size: 12px;
  color: var(--td-text-placeholder);
  padding: 6px 14px 0;
}

.ct__input {
  padding: 12px 14px;
  border-top: 1px solid var(--td-component-stroke);
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.ct__send {
  height: 38px;
  flex-shrink: 0;
}
</style>
