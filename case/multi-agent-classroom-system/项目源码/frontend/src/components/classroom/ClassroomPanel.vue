<script setup lang="ts">
/**
 * 课堂右侧面板：**字幕 / 讨论 / 课程大纲 / 白板** 四个 Tab（F3-3 / F3-4 / F3-10 / F3-9）。
 *
 * 版式取自 `产品原型/classroom.html`（原型是三个 Tab，字幕在舞台下面 ——
 * 这里多出一个「字幕」页，因为它在那儿只能显示一行，而 P3 要的是
 * 「当前 beat 高亮 + 历史字幕滚动 + 点历史跳回那一页」三件事）。
 *
 * **课堂状态一律从 store 读**（`useClassroomStore`），不由父组件一层层传进来：
 * 这一块要显示的消息、字幕、举手队列、板书、题面有二十来个字段，全写成 props
 * 之后「面板显示了什么」与「课堂是什么样」这两件事就得手工对齐，而它们本来就是
 * 同一件事。父组件只往下传**动作**（`emit`）与**传输状态**（连没连上）。
 *
 * 面板自己发起的 HTTP 读取（翻看别页的板书）直接写进 store —— 那是同一份
 * 服务端数据从另一条路进来，不是本地伪造状态（见 `stores/classroom.ts`）。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

import ClassroomBoard from '@/components/classroom/ClassroomBoard.vue'
import { fetchBoard } from '@/api/classroom'
import { useVoiceRecorder } from '@/composables/useVoiceRecorder'
import { useClassroomStore } from '@/stores/classroom'
import { useSettingsStore } from '@/stores/settings'
import {
  avatarColor,
  badgeOf,
  clockOf,
  isSystemMessage,
  memberColor,
  speakerNamer,
} from '@/utils/classroom'
import type { ClassroomMessage } from '@/types/classroom'

const props = withDefaults(
  defineProps<{
    /** 通道连上了没有。没连上时输入区禁用并说明原因。 */
    connected?: boolean
    /** 此刻能不能互动（`idle` 之外的活课才谈得上举手与提问） */
    interactive?: boolean
  }>(),
  { connected: false, interactive: false },
)

const emit = defineEmits<{
  jump: [pageNo: number]
  hand: [action: 'raise' | 'lower']
  ask: [payload: { text: string; mode: 'voice' | 'text'; quoteMsgId: string }]
}>()

const store = useClassroomStore()
const settings = useSettingsStore()

// --- Tab ---

const tab = ref('subtitle')

// --- 角色与头像色 ---

// 说话人的名与色、消息徽标、时间：都在 `utils/classroom` 里 ——
// 课堂页与记录页看的是同一条消息，两页必须给出同一种读法
const whoOf = computed(() => speakerNamer(settings.roles))

const isSystem = isSystemMessage

// --- 字幕 Tab ---

/** 历史字幕倒着排：最近说的在最上面，不用滚。 */
const historySubtitles = computed(() => [...store.subtitles].reverse())

/** 当前这一条字幕的 beatId —— 列表里把它点亮。 */
const liveBeatId = computed(
  () => store.speaking?.beats?.[0] || store.currentSubtitle?.beatId || '',
)

// --- 讨论 Tab ---

const quote = ref<ClassroomMessage | null>(null)
const draft = ref('')

/** 一次引用：把这条消息挂到输入框上，下一条提问带上它（F3-4 的「至少可引用」）。 */
function toggleQuote(message: ClassroomMessage) {
  quote.value = quote.value?.id === message.id ? null : message
}

function sendText() {
  const text = draft.value.trim()
  if (!text) return
  emit('ask', { text, mode: 'text', quoteMsgId: quote.value?.id ?? '' })
  draft.value = ''
  quote.value = null
}

// --- 被点名 → 弹提问条并自动开始录音（F3-7 / §6）---

const composer = ref(false)
const recorder = useVoiceRecorder({
  // 录满自动收工：把识别按钮摆回来，别让人以为还能接着说
  onAutoStop: () => void stopRecording(),
})

const recording = recorder.recording
const transcribing = recorder.busy

async function startRecording(): Promise<void> {
  if (!props.connected) return
  const ok = await recorder.start()
  if (!ok) MessagePlugin.warning(recorder.error.value || '打不开麦克风，可以打字提问。')
}

/** 松开 → 识别 → 把文字填进输入框，**由学生确认之后再发**。 */
async function stopRecording(): Promise<void> {
  if (!recorder.recording.value) return
  const said = await recorder.stop()
  if (said) draft.value = draft.value ? `${draft.value} ${said}` : said
  else if (recorder.error.value) MessagePlugin.warning(recorder.error.value)
}

/**
 * 被点到名就弹提问条。**不自动开麦**：浏览器要求用户先有一次交互才允许
 * 开麦克风，替用户按下那一下得到的多半是一条被拒的提示，比让他自己点更糟。
 * 所以这里只把条弹出来、把焦点放上去，录音键上写清「该你了」。
 */
watch(
  () => store.iAmCalled,
  async (called) => {
    if (!called) return
    composer.value = true
    tab.value = 'discuss'
    await nextTick()
    MessagePlugin.info('老师点到你了 —— 按住「按住说话」提问，或者直接打字')
  },
)

// --- 举手 ---

const raised = computed(() => store.myHandPosition > 0)

function toggleHand() {
  if (!props.interactive) return
  emit('hand', raised.value ? 'lower' : 'raise')
}

/** 举手按钮上的话：位次由服务端的 `hand_queue` 说了算，这里只是它的一句话。 */
const handLabel = computed(() => {
  if (store.called) return '老师正在等你提问'
  if (raised.value) return `已举手（第 ${store.myHandPosition} 位）`
  return '举手提问'
})

const handQueueLabel = computed(() => {
  const others = store.handQueue.filter((item) => item.userId !== store.ownerId)
  if (!others.length) return ''
  return `后面还有 ${others.length} 位`
})

// --- 大纲 Tab ---

/**
 * 大纲按章分组。分组从**课堂时间线**来（`timeline.pages[].chapterNo`），
 * 不是从 `/outline` —— 课堂上能跳到哪一页，取决于这门课有哪些页是可讲的
 * （P1 的 `status=ready` 才算），拿大纲树来列会列出跳不过去的页。
 */
const chapters = computed(() => {
  const groups: { no: number; title: string; pages: typeof store.pages }[] = []
  for (const page of store.pages) {
    const last = groups[groups.length - 1]
    if (last && last.no === page.chapterNo) {
      last.pages = [...last.pages, page]
      continue
    }
    groups.push({ no: page.chapterNo, title: chapterTitle(page.chapterNo), pages: [page] })
  }
  return groups
})

function chapterTitle(no: number): string {
  if (no <= 0) return ''
  return `第 ${no} 章`
}

const seen = (pageNo: number) => store.pageNo > 0 && pageNo < store.pageNo

// --- 白板 Tab ---

/**
 * 板书的「按页切换」（F3-9）。
 *
 * 列的只是**有板书画笔的页**（`timeline.pages[].boardPlan` 非空）——
 * 让老师为翻一页白板而把课翻走是没有道理的，所以这里自己有一份浏览页号，
 * 与课堂当前页分开：翻看旧板书不动课堂。
 */
const boardPages = computed(() =>
  store.pages.filter((page) => (page.boardPlan?.length ?? 0) > 0).map((page) => page.pageNo),
)

const boardPageNo = ref(0)
const boardLoading = ref(false)
const replayKey = ref(0)

/** 默认看**课堂当前这一页**；这一页没板书就退到最近的有板书的一页。 */
watch(
  () => [store.pageNo, boardPages.value] as const,
  () => {
    if (boardPages.value.includes(store.pageNo)) {
      boardPageNo.value = store.pageNo
      return
    }
    if (!boardPageNo.value || !boardPages.value.includes(boardPageNo.value)) {
      boardPageNo.value = boardPages.value[0] ?? 0
    }
  },
  { immediate: true },
)

/** 那一页的笔画。课上推过来的直接有；翻看别的页要自己问一次。 */
const boardStrokes = computed(() => store.boards[boardPageNo.value] ?? [])

async function loadBoard(pageNo: number): Promise<void> {
  if (!store.sessionId || !pageNo || store.boards[pageNo]) return
  boardLoading.value = true
  try {
    const result = await fetchBoard(store.sessionId, pageNo)
    store.applyBoard(pageNo, result.strokes)
  } catch {
    // 读不出来就是空板：白板 Tab 不该因为一次读失败把整页顶掉
  } finally {
    boardLoading.value = false
  }
}

watch(boardPageNo, (pageNo) => void loadBoard(pageNo), { immediate: true })
watch(() => store.sessionId, (id) => { if (id) void loadBoard(boardPageNo.value) })

function stepBoard(offset: number) {
  const at = boardPages.value.indexOf(boardPageNo.value)
  const next = boardPages.value[at + offset]
  if (next) boardPageNo.value = next
}

/**
 * 「同步给全班」在 P3 是**本地开关**（F3-9 的原话）。
 *
 * 做成开关而不是一个动作，是因为它描述的是「我接下来的标注要不要给大家看」
 * 这个状态 —— 而 P3 还没有在这张白板上落笔的能力（那要 P6 的标注），
 * 所以它现在只是一个记着的位置，不假装已经同步出去了。
 */
const syncOn = ref(false)

function toggleSync() {
  syncOn.value = !syncOn.value
  MessagePlugin.info(
    syncOn.value
      ? '已打开「同步给全班」——P3 期间这是本地开关，白板上的标注能力在 P6 接入'
      : '已关闭「同步给全班」',
  )
}

// --- 在线（F3-12）---

/**
 * 在线人数用服务端的 `presence.online`。**不再用「角色数 + 1」估**：
 * 那个数在一堂真的课上是错的（关掉一个标签页不会少一个人）。
 */
const onlineCount = computed(() => store.presence.online)

const members = computed(() => store.presence.members)

/**
 * 这堂课里的 AI 同学（人数由设置页「AI 同学数量」决定，服务端按它取角色）。
 *
 * 它们**不算在 `online` 里**：那个数是「几个人真的连进来了」，用来判断学生
 * 到齐没有；AI 同学不连进来，它们一直都在。所以顶栏上分成两个数看。
 */
const aiMembers = computed(() => store.presence.aiMembers)

const presenceTitle = computed(() => {
  if (!aiMembers.value.length) return `${onlineCount.value} 人正在这堂课里`
  return (
    `${onlineCount.value} 位真人在线；另有 ${aiMembers.value.length} 位 AI 同学，` +
    '讨论环节由 TA 们发言（人数在设置页「AI 同学数量」里调）'
  )
})

function colorOfMember(member: { userId: string; role: string }): string {
  return memberColor(member, store.ownerId, settings.roles)
}

/**
 * 名单上写谁的名字。**用服务端给的名字，不是 `role`** ——
 * 那个字段是权限（`owner` / `member`），写在头像下面就是「owner 在线了」。
 * 名字现查（`recorder.names_of`），改昵称之后整块名单一起跟着变。
 */
function nameOfMember(member: { userId: string; name: string; role: string }): string {
  if (member.userId === store.ownerId) return '我'
  return member.name || member.role
}

/** AI 同学的色：服务端按角色给的 `color`，没配就按 code 现算一个（与消息头像同源）。 */
function colorOfAi(member: { code: string; color: string }): string {
  return member.color || avatarColor(member.code)
}

const recorderHint = computed(() => {
  if (recorder.error.value) return recorder.error.value
  return ''
})
</script>

<template>
  <aside class="side">
    <div class="side__tabs">
      <t-tabs v-model="tab">
        <t-tab-panel value="subtitle" label="字幕" />
        <t-tab-panel value="discuss" label="讨论" />
        <t-tab-panel value="outline" label="课程大纲" />
        <t-tab-panel value="board" label="白板" />
      </t-tabs>
      <t-tag theme="primary" variant="light" :title="presenceTitle">
        在线 {{ onlineCount }}
        <span v-if="aiMembers.length"> · AI {{ aiMembers.length }}</span>
      </t-tag>
    </div>

    <!-- ============ 字幕 ============ -->
    <div v-if="tab === 'subtitle'" class="pane">
      <div class="live-sub">
        <div class="live-sub__head">
          <t-tag theme="primary" variant="light">正在讲</t-tag>
          <span class="live-sub__who">{{ store.speaking?.speaker?.name ?? '' }}</span>
        </div>
        <div class="live-sub__text">
          {{ store.speaking?.text || store.currentSubtitle?.text || '老师还没有开口。' }}
        </div>
      </div>

      <div class="pane__body">
        <div class="sub-list">
          <div
            v-for="line in historySubtitles"
            :key="line.beatId"
            class="sub-item"
            :class="{ 'is-live': line.beatId === liveBeatId }"
            :title="`跳到第 ${line.pageNo} 页`"
            @click="emit('jump', line.pageNo)"
          >
            <span class="sub-item__no">{{ String(line.pageNo).padStart(2, '0') }}</span>
            <span class="sub-item__text">{{ line.text }}</span>
          </div>
          <t-empty
            v-if="!historySubtitles.length"
            size="small"
            description="讲稿字幕会一行一行落在这里，点任意一行可以跳回它所在的页。"
          />
        </div>
      </div>
    </div>

    <!-- ============ 讨论 ============ -->
    <div v-else-if="tab === 'discuss'" class="pane">
      <div class="agents-strip">
        <div v-for="member in members" :key="member.userId" class="agent-chip">
          <t-avatar :style="{ background: colorOfMember(member) }" shape="circle" size="small">
            {{ nameOfMember(member).slice(0, 1) }}
          </t-avatar>
          <span class="name">{{ nameOfMember(member) }}</span>
        </div>
        <div v-if="members.length && aiMembers.length" class="agents-strip__sep" />
        <!-- AI 同学：讨论里真的会开口的几位，按设置页「AI 同学数量」取前 N 位 -->
        <div
          v-for="mate in aiMembers"
          :key="mate.code"
          class="agent-chip agent-chip--ai"
          :title="`AI 同学 ${mate.name}：讨论环节由 TA 发言`"
        >
          <t-avatar :style="{ background: colorOfAi(mate) }" shape="circle" size="small">
            {{ mate.name.slice(0, 1) }}
          </t-avatar>
          <span class="name">{{ mate.name }}</span>
        </div>
        <div v-if="!members.length && !aiMembers.length" class="agents-strip__empty">
          还没有人进来
        </div>
      </div>

      <div class="chat">
        <template v-if="store.messages.length">
          <template v-for="message in store.messages" :key="message.id">
            <div v-if="isSystem(message)" class="msg--sys">{{ message.text }}</div>
            <div
              v-else
              class="msg"
              :class="[
                message.speakerKind === 'me' ? 'msg--me' : 'msg--other',
                { 'is-quoted': quote?.id === message.id },
              ]"
              :title="'点一下引用这条发言'"
              @click="toggleQuote(message)"
            >
              <div class="msg__head">
                <t-avatar :style="{ background: whoOf(message).color }" shape="circle" size="16px">
                  {{ whoOf(message).name.slice(0, 1) }}
                </t-avatar>
                <span class="msg__who">{{ whoOf(message).name }}</span>
                <t-tag v-if="message.type !== 'lecture'" size="small" variant="light" :theme="badgeOf(message).theme">
                  {{ badgeOf(message).text }}
                </t-tag>
                <span class="msg__time">{{ clockOf(message.ts) }}</span>
              </div>
              <div class="msg__text">{{ message.text }}</div>
              <div v-if="message.quoteMsgId" class="msg__quote">引用了上一条发言</div>
            </div>
          </template>
        </template>
        <template v-else>
          <div class="msg--sys">课堂还没有开始 · 点右上角「开始上课」</div>
          <t-empty
            size="small"
            description="老师的讲解、AI 同学的提问与补充都会落在这里，点任意一条可以引用它提问。"
          />
        </template>

        <!-- 「正在输入…」：`typing` 事件驱动（§6）。静默发言（不点名老师的讨论
             发言）不发 `speak`，那一条全靠它表现得出来。 -->
        <div v-if="store.typing" class="typing">
          <span class="typing__who">{{ store.typing.speaker.name }}</span>
          <span class="typing__dots"><i /><i /><i /></span>
        </div>
      </div>

      <t-alert v-if="recorderHint" theme="warning" class="chat-hint">
        <template #message>{{ recorderHint }}</template>
      </t-alert>

      <div class="chat-input">
        <div class="hand-row">
          <div
            class="raise-hand"
            :class="{ 'is-raised': raised, 'is-disabled': !interactive }"
            :title="interactive ? '举手（也可以按空格）' : '课堂还没开始'"
            @click="toggleHand"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path
                d="M7 11V5.5a1.5 1.5 0 0 1 3 0V10m0-4.5v-1a1.5 1.5 0 0 1 3 0V10m0-4.5a1.5 1.5 0 0 1 3 0V12m0-3a1.5 1.5 0 0 1 3 0v5a6 6 0 0 1-6 6h-1.4a6 6 0 0 1-4.8-2.4L4 15.6a1.6 1.6 0 0 1 2.6-1.9L7 14.5"
              />
            </svg>
            <span>{{ handLabel }}</span>
          </div>
          <span v-if="handQueueLabel" class="hand-note">{{ handQueueLabel }}</span>
        </div>

        <div v-if="quote" class="quote-bar">
          <span class="quote-bar__label">引用</span>
          <span class="quote-bar__text">{{ quote.text }}</span>
          <span class="quote-bar__close" @click="quote = null">×</span>
        </div>

        <div class="box">
          <t-textarea
            v-model="draft"
            :autosize="{ minRows: 2, maxRows: 4 }"
            :disabled="!connected"
            :placeholder="connected ? '打字提问或发言；点名老师时老师会作答' : '与课堂的连接还没建起来'"
          />
          <t-button theme="primary" :disabled="!connected || !draft.trim()" @click="sendText">
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" />
              </svg>
            </template>
            发送
          </t-button>
        </div>

        <button
          class="push-to-talk"
          :class="{ 'is-live': recording }"
          :disabled="!connected || transcribing"
          :title="
            connected
              ? '按住说话，松开后识别成文字（识别结果会填进上面的输入框，确认后再发）'
              : '与课堂的连接还没建起来'
          "
          @mousedown="startRecording()"
          @mouseup="stopRecording()"
          @mouseleave="recording && stopRecording()"
          @touchstart.prevent="startRecording()"
          @touchend.prevent="stopRecording()"
        >
          <span class="dot" />
          {{
            transcribing
              ? '正在识别…'
              : recording
                ? `松开发送（已录 ${(recorder.elapsedMs.value / 1000).toFixed(1)}s）`
                : '按住说话'
          }}
        </button>

        <button v-if="!composer && store.iAmCalled" class="called" @click="composer = true">
          老师点到你了 —— 点这里提问
        </button>
      </div>
    </div>

    <!-- ============ 课程大纲 ============ -->
    <div v-else-if="tab === 'outline'" class="pane">
      <div class="pane__body">
        <div v-if="chapters.length" class="outline">
          <div v-for="group in chapters" :key="group.no" class="outline__chapter">
            <div v-if="group.title" class="outline__chapter-title">{{ group.title }}</div>
            <div
              v-for="item in group.pages"
              :key="item.pageNo"
              class="outline__page"
              :class="{ 'is-current': item.pageNo === store.pageNo }"
              @click="emit('jump', item.pageNo)"
            >
              <span class="no">{{ String(item.pageNo).padStart(2, '0') }}</span>
              <span class="title">{{ item.title }}</span>
              <svg
                v-if="seen(item.pageNo)"
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

    <!-- ============ 白板 ============ -->
    <div v-else class="pane">
      <div class="board-head">
        <t-button size="small" variant="outline" :disabled="!boardPages.length" @click="stepBoard(-1)">
          上一页
        </t-button>
        <span class="board-head__no">
          第 <b>{{ boardPageNo || '—' }}</b> 页板书
          <span v-if="boardPageNo && boardPageNo !== store.pageNo" class="board-head__away">
            （讲台在第 {{ store.pageNo }} 页）
          </span>
        </span>
        <t-button size="small" variant="outline" :disabled="!boardPages.length" @click="stepBoard(1)">
          下一页
        </t-button>
      </div>

      <ClassroomBoard
        :strokes="boardStrokes"
        :replay-key="replayKey"
        :live="boardPageNo === store.pageNo"
        :loading="boardLoading"
      />

      <div class="whiteboard__tools">
        <t-button size="small" @click="replayKey += 1">
          <template #icon>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" />
            </svg>
          </template>
          回看本页板书
        </t-button>
        <span class="spacer" />
        <t-button size="small" :theme="syncOn ? 'primary' : 'default'" @click="toggleSync">
          <template #icon>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" />
            </svg>
          </template>
          {{ syncOn ? '已同步给全班' : '同步给全班' }}
        </t-button>
      </div>
    </div>
  </aside>
</template>
<style scoped src="../../styles/components/classroom/ClassroomPanel.css"></style>
