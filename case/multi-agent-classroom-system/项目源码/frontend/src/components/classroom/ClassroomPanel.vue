<script setup lang="ts">
/**
 * 课堂右侧面板：讨论 / 课程大纲 / 白板。
 *
 * 版式取自 `产品原型/classroom.html`。这里：
 * - 成员条是**真的**：老师与 AI 同学来自 /api/roles 的种子数据，头像用角色自己的颜色
 * - 课程大纲是**真的**：整棵章节树来自 /outline，点一下就跳到那一页
 * - 消息区、白板是空状态，不塞演示对话（课堂运行时在 P3）
 * 保留整套骨架是为了让 P3 有地方长，也让空状态看起来像「还没开始」而不是「页面坏了」。
 */
import { computed, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

import { useSettingsStore } from '@/stores/settings'
import type { OutlinePageItem, OutlineTree } from '@/types/api'

const props = withDefaults(
  defineProps<{
    outline?: OutlineTree | null
    /** 舞台上正在讲第几页（大纲里高亮它，翻过的打勾） */
    currentNo?: number
  }>(),
  { outline: null, currentNo: 0 },
)

const emit = defineEmits<{ jump: [pageNo: number] }>()

const settings = useSettingsStore()

/**
 * 大纲按「开篇页 → 各章 → 收尾页」排。章号 0 的封面与大纲页在服务端被摘进
 * `front`、收尾页进 `back`（P1 §3.3），所以它们没有章标题 —— 不硬安一个。
 */
const groups = computed(() => {
  const tree = props.outline
  if (!tree) return []
  return [
    { key: 'front', title: '', pages: tree.front },
    ...tree.chapters.map((chapter) => ({
      key: `ch-${chapter.no}`,
      title: chapter.title,
      pages: chapter.pages,
    })),
    { key: 'back', title: '', pages: tree.back },
  ].filter((group) => group.pages.length > 0)
})

const pad = (no: number) => String(no).padStart(2, '0')

/** 翻过的页给个勾：原型在大纲上也是这么标进度的（这里标的是「翻到过」）。 */
const seen = (page: OutlinePageItem) => props.currentNo > 0 && page.pageNo < props.currentNo

const tab = ref('discuss')
const chatText = ref('')
const raised = ref(false)

/** 在线人数 = 角色库里的教师 + AI 同学 + 我。 */
const onlineCount = computed(() => settings.roles.length + 1)

const BOARD_TOOLS = [
  { key: 'pen', title: '画笔' },
  { key: 'text', title: '文本' },
  { key: 'shape', title: '图形' },
  { key: 'eraser', title: '橡皮' },
] as const

const boardTool = ref('pen')

function todo(what: string) {
  MessagePlugin.info(`${what}将在 P3 阶段接入（课堂运行时）`)
}

function raiseHand() {
  raised.value = !raised.value
  MessagePlugin.info(
    raised.value
      ? '已举手 —— 课堂运行在 P3 接入后，教师会真的点名'
      : '已取消举手',
  )
}
</script>

<template>
  <aside class="side">
    <div class="side__tabs">
      <t-tabs v-model="tab">
        <t-tab-panel value="discuss" label="讨论" />
        <t-tab-panel value="outline" label="课程大纲" />
        <t-tab-panel value="board" label="白板" />
      </t-tabs>
      <t-tag theme="primary" variant="light">在线 {{ onlineCount }}</t-tag>
    </div>

    <!-- 讨论 -->
    <div v-if="tab === 'discuss'" class="pane">
      <div class="agents-strip">
        <div v-for="role in settings.roles" :key="role.id" class="agent-chip">
          <t-avatar :style="{ background: role.avatarColor }" shape="circle">
            {{ role.name.slice(0, 1) }}
          </t-avatar>
          <span class="name">{{ role.name }}</span>
          <span class="role-label">{{ role.role === 'teacher' ? 'AI 教师' : 'AI 同学' }}</span>
        </div>
        <div class="agent-chip">
          <t-avatar :style="{ background: 'linear-gradient(135deg,#333,#666)' }" shape="circle">
            我
          </t-avatar>
          <span class="name">我</span>
          <span class="role-label">学生</span>
        </div>
      </div>

      <div class="chat">
        <div class="msg--sys">课堂还没有开始 · 生成课程后在这里开课</div>
        <t-empty
          size="small"
          description="AI 教师讲解、AI 同学提问、你的发言都会出现在这里 —— 课堂运行时在 P3 阶段接入。"
        />
      </div>

      <div class="chat-input">
        <div class="raise-hand" :class="{ 'is-raised': raised }" @click="raiseHand">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path
              d="M7 11V5.5a1.5 1.5 0 0 1 3 0V10m0-4.5v-1a1.5 1.5 0 0 1 3 0V10m0-4.5a1.5 1.5 0 0 1 3 0V12m0-3a1.5 1.5 0 0 1 3 0v5a6 6 0 0 1-6 6h-1.4a6 6 0 0 1-4.8-2.4L4 15.6a1.6 1.6 0 0 1 2.6-1.9L7 14.5"
            />
          </svg>
          <span>{{ raised ? '已举手，等待点名…' : '举手提问' }}</span>
        </div>
        <div class="box">
          <t-textarea
            v-model="chatText"
            :autosize="{ minRows: 2, maxRows: 4 }"
            placeholder="向老师或同学提问（课堂运行时在 P3 接入）"
          />
          <t-button theme="primary" @click="todo('发送消息')">
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" />
              </svg>
            </template>
            发送
          </t-button>
        </div>
      </div>
    </div>

    <!-- 课程大纲 -->
    <div v-else-if="tab === 'outline'" class="pane">
      <div class="pane__body">
        <div v-if="groups.length" class="outline">
          <div v-for="group in groups" :key="group.key" class="outline__chapter">
            <div v-if="group.title" class="outline__chapter-title">{{ group.title }}</div>
            <div
              v-for="item in group.pages"
              :key="item.pageNo"
              class="outline__page"
              :class="{ 'is-current': item.pageNo === currentNo }"
              @click="emit('jump', item.pageNo)"
            >
              <span class="no">{{ pad(item.pageNo) }}</span>
              <span class="title">{{ item.title }}</span>
              <svg
                v-if="seen(item)"
                class="done"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </div>
          </div>
        </div>
        <t-empty v-else size="small" description="课程大纲会在这里按章节展开，点击可跳页" />
      </div>
    </div>

    <!-- 白板 -->
    <div v-else class="pane">
      <div class="whiteboard">
        <div class="whiteboard__canvas">
          <t-empty size="small" description="AI 教师板书与标注会出现在这里" />
        </div>
        <div class="whiteboard__tools">
          <span
            v-for="tool in BOARD_TOOLS"
            :key="tool.key"
            class="wb-tool"
            :class="{ 'is-active': boardTool === tool.key }"
            :title="tool.title"
            @click="boardTool = tool.key"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <path v-if="tool.key === 'pen'" d="m14 6 4 4L8.5 19.5a2.1 2.1 0 0 1-3-3L14 6ZM16 4l4 4" />
              <path v-else-if="tool.key === 'text'" d="M5 6V4h14v2M12 4v16M9 20h6" />
              <template v-else-if="tool.key === 'shape'">
                <rect x="4" y="4" width="10" height="10" rx="1" />
                <circle cx="16" cy="16" r="5" />
              </template>
              <path v-else d="m9 15 8.5-8.5a2.1 2.1 0 0 1 3 3L12 18H8l-3 3h13" />
            </svg>
          </span>
          <span class="spacer" />
          <span class="wb-tool" title="同步给全班" @click="todo('同步板书')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" />
            </svg>
          </span>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.side {
  width: 380px;
  flex-shrink: 0;
  background: var(--td-bg-container);
  border-left: 1px solid var(--td-component-stroke);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.side__tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-right: 12px;
  border-bottom: 1px solid var(--td-component-stroke);
  flex-shrink: 0;
}

.side__tabs :deep(.t-tabs) {
  flex: 1;
  min-width: 0;
}

.side__tabs :deep(.t-tabs__nav-wrap) {
  border-bottom: none;
}

.pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* --- 成员条 --- */
.agents-strip {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--td-component-stroke);
  overflow-x: auto;
  flex-shrink: 0;
}

.agent-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 8px 6px;
  border-radius: var(--td-radius-medium);
  min-width: 68px;
}

.agent-chip .name {
  font-size: 12px;
  color: var(--td-text-primary);
}

.agent-chip .role-label {
  font-size: 11px;
  color: var(--td-text-placeholder);
}

/* --- 消息区 --- */
.chat {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: var(--td-bg-page);
}

.msg--sys {
  align-self: center;
  font-size: 12px;
  color: var(--td-text-placeholder);
  background: rgba(0, 0, 0, 0.04);
  padding: 4px 12px;
  border-radius: var(--td-radius-round);
}

/* --- 输入区 --- */
.chat-input {
  padding: 12px 16px 16px;
  border-top: 1px solid var(--td-component-stroke);
  flex-shrink: 0;
}

.chat-input .box {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.chat-input .box :deep(.t-textarea) {
  flex: 1;
}

.raise-hand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 32px;
  padding: 0 12px;
  border-radius: var(--td-radius-round);
  cursor: pointer;
  border: 1px solid var(--td-warning-color);
  color: var(--td-warning-color);
  background: var(--td-warning-color-light);
  font-size: 13px;
  transition: all 0.2s;
  margin-bottom: 10px;
  width: fit-content;
}

.raise-hand.is-raised {
  background: var(--td-warning-color);
  color: var(--td-text-anti);
}

/* --- 大纲 / 白板 --- */
.pane__body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* 有内容时由 .outline 撑满；空状态靠 auto 外边距居中 */
.pane__body :deep(.t-empty) {
  margin: auto;
}

/* 大纲（原型 .outline__*） */
.outline__chapter {
  margin-bottom: 6px;
}

.outline__chapter-title {
  padding: 9px 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--td-text-primary);
}

.outline__page {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 8px 30px;
  border-radius: var(--td-radius-default);
  font-size: 13px;
  color: var(--td-text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}

.outline__page:hover {
  background: var(--td-bg-container-hover);
}

.outline__page.is-current {
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
  font-weight: 500;
}

.outline__page .no {
  font-family: var(--td-font-mono);
  font-size: 11px;
  width: 22px;
  flex-shrink: 0;
  color: var(--td-text-placeholder);
}

.outline__page.is-current .no {
  color: var(--td-brand-color);
}

.outline__page .title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.outline__page .done {
  flex-shrink: 0;
  color: var(--td-success-color);
}

.whiteboard {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--td-bg-page);
  min-height: 0;
}

.whiteboard__canvas {
  flex: 1;
  margin: 14px;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
}

.whiteboard__tools {
  display: flex;
  gap: 6px;
  padding: 0 14px 14px;
  flex-shrink: 0;
}

.whiteboard__tools .spacer {
  flex: 1;
}

.whiteboard__tools .wb-tool {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-default);
  box-shadow: var(--td-shadow-1);
  cursor: pointer;
  color: var(--td-text-secondary);
}

.whiteboard__tools .wb-tool.is-active {
  color: var(--td-brand-color);
  outline: 1px solid var(--td-brand-color);
}

.whiteboard__tools .wb-tool svg {
  width: 16px;
  height: 16px;
}
</style>
