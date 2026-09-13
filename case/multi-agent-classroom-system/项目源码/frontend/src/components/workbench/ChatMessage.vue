<script setup lang="ts">
/**
 * 会话里的一条消息（版式照 `产品原型/workbench.html` 的 `.wb-msg`）。
 *
 * 我发的靠右（品牌色），Agent 发的靠左（白底）。Agent 那条底下挂操作卡 ——
 * 「说了什么」和「做了什么」在同一个气泡里，回看时不用去两个地方对时间。
 *
 * **「回到这里」是回退上下文，不是撤销**：回退会丢掉这条及其后的消息，
 * 页面内容不动（语义在 `chat.py` 里写死了，前端只负责把话说清楚）。
 * 所以确认框里两件事都写：丢几条、以及「课程内容不会跟着回退」。
 */
import { computed } from 'vue'
import { DialogPlugin } from 'tdesign-vue-next'

import SkillCard from '@/components/workbench/SkillCard.vue'
import type { CardView } from '@/composables/useWorkbenchChat'
import type { ChatMessageItem } from '@/types/api'

const props = defineProps<{
  message: ChatMessageItem
  /** 正文。正在流式出现的是本地攒的那些字，不在 `message.content` 里。 */
  text: string
  /** 这一条的操作卡（可能来自流、也可能来自库里的 `skillCalls`）。 */
  cards: CardView[]
  /** 技能名 → 中文名。 */
  titles: Record<string, string>
  /** 这一轮还没跑完（气泡上挂一个转圈的点）。 */
  streaming: boolean
  /** 这条及其后还有几条消息 —— 回退确认框里的那个数字。 */
  tailCount: number
}>()

const emit = defineEmits<{
  rollback: [messageId: string]
  openPage: [pageNo: number]
  openSource: [source: Record<string, unknown>]
}>()

const mine = computed(() => props.message.role === 'user')

/** 头像取自原型（内联渐变收成常量）。 */
const AVATAR_ME = 'linear-gradient(135deg,#333,#666)'
const AVATAR_AI = 'linear-gradient(135deg,#0052d9,#618eff)'

/**
 * 回退确认。用的是 TDesign 的 `DialogPlugin`：它挂在 body 上，不会被
 * 左栏的滚动容器裁掉。
 */
function askRollback(): void {
  const count = Math.max(props.tailCount, 1)
  const dialog = DialogPlugin.confirm({
    header: '回到这里？',
    body: `将丢弃这条以及它之后的 ${count} 条消息，之后的对话不再记得这一段。课程内容不会跟着回退 —— 要撤销页面改动，请用页面自己的版本号。`,
    confirmBtn: '回退',
    cancelBtn: '再想想',
    onConfirm: () => {
      emit('rollback', props.message.id)
      dialog.destroy()
    },
    onCancel: () => dialog.destroy(),
  })
}
</script>

<template>
  <div class="wb-msg" :class="{ 'wb-msg--me': mine }">
    <t-avatar class="wb-msg__avatar" shape="circle" :style="{ background: mine ? AVATAR_ME : AVATAR_AI }">
      {{ mine ? '我' : 'AI' }}
    </t-avatar>

    <div class="wb-msg__body">
      <div v-if="message.refPageNo" class="wb-msg__ref">针对第 {{ message.refPageNo }} 页</div>

      <div class="wb-msg__bubble">
        <template v-if="text">{{ text }}</template>
        <span v-else-if="streaming" class="wb-msg__typing"><i /><i /><i /></span>
        <span v-else class="wb-msg__empty">（这条没有文字内容）</span>
      </div>

      <SkillCard
        v-for="(card, index) in cards"
        :key="`${card.skill}-${index}`"
        class="wb-msg__card"
        :skill="card.skill"
        :title="titles[card.skill] ?? card.skill"
        :args="card.args ?? {}"
        :why="card.why ?? ''"
        :status="card.status"
        :result="card.result ?? null"
        :error="card.error ?? ''"
        :duration-ms="card.durationMs ?? 0"
        @open-page="emit('openPage', $event)"
        @open-source="emit('openSource', $event)"
      />

      <div class="wb-msg__foot">
        <button
          v-if="!streaming"
          class="wb-msg__back"
          title="丢弃这条及其后的消息，从这一刻重新开始"
          @click="askRollback"
        >
          回到这里
        </button>
        <span v-if="message.tokens" class="text-placeholder wb-msg__tokens mono">
          {{ message.tokens }} tokens
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 版式取自 产品原型/workbench.html 的 .wb-msg */
.wb-msg {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.wb-msg--me {
  flex-direction: row-reverse;
}

.wb-msg__avatar {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  font-size: 12px;
  color: #fff;
}

.wb-msg__body {
  min-width: 0;
  max-width: calc(100% - 40px);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.wb-msg--me .wb-msg__body {
  align-items: flex-end;
}

.wb-msg__ref {
  font-size: 11px;
  color: var(--td-text-placeholder);
  padding: 0 2px;
}

.wb-msg__bubble {
  background: var(--td-bg-container);
  padding: 10px 12px;
  border-radius: 2px 8px 8px 8px;
  font-size: 13.5px;
  line-height: 1.7;
  box-shadow: var(--td-shadow-1);
  white-space: pre-wrap;
  word-break: break-word;
}

.wb-msg--me .wb-msg__bubble {
  background: var(--td-brand-color);
  color: #fff;
  border-radius: 8px 2px 8px 8px;
}

.wb-msg__empty {
  color: var(--td-text-placeholder);
  font-size: 12.5px;
}

.wb-msg--me .wb-msg__empty {
  color: rgba(255, 255, 255, 0.75);
}

/* 打字机那三个点：只在「这一轮在跑但还没有字」时出现 */
.wb-msg__typing {
  display: inline-flex;
  gap: 3px;
  align-items: center;
}

.wb-msg__typing i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--td-text-placeholder);
  animation: blink 1.2s infinite;
}

.wb-msg__typing i:nth-child(2) {
  animation-delay: 0.2s;
}

.wb-msg__typing i:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes blink {
  0%,
  60%,
  100% {
    opacity: 0.25;
  }
  30% {
    opacity: 1;
  }
}

.wb-msg__card {
  width: 100%;
}

.wb-msg__foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 2px;
  min-height: 16px;
}

.wb-msg--me .wb-msg__foot {
  flex-direction: row-reverse;
}

.wb-msg__back {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 11.5px;
  color: var(--td-text-placeholder);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s;
}

.wb-msg:hover .wb-msg__back {
  opacity: 1;
}

.wb-msg__back:hover {
  color: var(--td-brand-color);
}

.wb-msg__tokens {
  font-size: 11px;
}

.mono {
  font-family: var(--td-font-mono);
}
</style>
