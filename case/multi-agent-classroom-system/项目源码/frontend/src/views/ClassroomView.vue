<script setup lang="ts">
/**
 * 课堂（P3-5）：**这一页是课堂运行时的客户端**。
 *
 * 版式照 `产品原型/classroom.html`（顶栏 + 左舞台 + 右面板），但内容与驱动方式
 * 全是 P3 的：课由服务端的 `POST /sessions` 开出来，之后每一步——讲到哪一页、
 * 谁在说话、什么时候弹题、谁被点名——都由 `/ws/classroom/{sessionId}` 上的
 * 事件流说了算。这一页自己不推算任何课堂状态（见 `stores/classroom.ts` 的纪律）。
 *
 * 这一层做四件事，别的都在别处：
 *
 * 1. **开课与恢复**。`开始上课` → `POST /sessions`（拿会话 + 票据 + 时间线）→
 *    建连；刷新后先用 `sessionStorage` 里的游标认出「还是这堂课」，再问一次
 *    `GET /sessions/{id}` 把位置拿回来（P3-A10）。
 * 2. **把事件流接到 store**，并把「该发出的上行」发出去：翻页 → `seek`、
 *    播/停 → `play`/`pause`、倍速 → `speed`、答完一句 → `beat_done`、
 *    举手/发言 → `hand`/`ask`/`chat`。上行全部经 `useClassroomSocket.send`，
 *    没连上时**静默丢掉**（理由见那个模块）。
 * 3. **出声**。`speak` 事件带音频 URL 就播、不带就只上屏（`useBeatPlayer`），
 *    并在这一句说完时报一次 `beat_done` —— 时间线是这么往前走的。
 * 4. **字幕的字级高亮**。课堂的字幕文字来自 `speak`（整句），逐词时间戳来自
 *    **音频清单**（`GET /audio-manifest` 里的 `subtitles` 按 `beatId` 对回来）。
 *    对不上就退整句：少一个动画，好过多一块和声音对不上的假高亮。
 *
 * **语音提问走 `POST /api/voice/asr`，不走 P2 的实时语音通道**：P2 那条路是
 * 「我对着麦克风说、老师流式回答」，它的答案只落在那个会话里；而课堂上老师
 * 的回答必须落在**这堂课的答案**里（`runtime._answer` 是唯一真相）。
 * 所以面板里是「录一段 → 出文字 → 确认发送」，走的是 `ask` 上行。
 *
 * 快捷键：**空格 = 举手/撤回**（P2 的「按住空格说话」在 P3 让位给举手 ——
 * 课堂里更常用的是它）、`←/→` 翻页、`Esc` 退出沉浸模式。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import ClassroomPanel from '@/components/classroom/ClassroomPanel.vue'
import ClassroomStage from '@/components/classroom/ClassroomStage.vue'
import QuizCard from '@/components/classroom/QuizCard.vue'
import * as api from '@/api'
import * as classroomApi from '@/api/classroom'
import { ApiError } from '@/api/client'
import { useBeatPlayer } from '@/composables/useBeatPlayer'
import { useClassroomSocket } from '@/composables/useClassroomSocket'
import { usePolling } from '@/composables/usePolling'
import { useClassroomStore, clearCursor, loadCursor, saveCursor } from '@/stores/classroom'
import { describeError, useSettingsStore } from '@/stores/settings'
import { CLASSROOM_STATUS_LABELS } from '@/utils/classroom'
import { noVoiceReason } from '@/utils/voice'
import type { AudioBeat, AudioManifest, CourseCard, CourseDetail } from '@/types/api'
import type { ClassroomEvent, ClassroomSummary } from '@/types/classroom'

const route = useRoute()
const router = useRouter()
const settings = useSettingsStore()
const store = useClassroomStore()
const {
  sessionId,
  status,
  pageNo,
  timeline,
  lastSeq,
  lastError,
  connection,
  presence,
} = storeToRefs(store)

/** 课程号写在地址栏上（首页/工作台点「进课堂」时带上）。 */
const courseId = computed(() => String(route.query.course ?? '').trim())
/** 直接指到某一堂课（从记录页「回到这堂课」之类的入口进来）。 */
const sessionQuery = computed(() => String(route.query.session ?? '').trim())

const course = ref<CourseDetail | null>(null)
const manifest = ref<AudioManifest | null>(null)
const candidates = ref<CourseCard[]>([])
const loading = ref(false)
const starting = ref(false)
const ending = ref(false)
const immersive = ref(false)
const loadError = ref('')
const quizSubmitting = ref(false)

/**
 * 能不能举手 / 发言。**跟着服务端的状态机走**（`live` = 不是 `idle` 也不是
 * `ended`）：`idle` 的会话上调 `hand` / `ask` 会被服务端按 40901 挡回来
 * （P3-B4），所以界面上就该是灰的，而不是按下去收一个红条。
 */
const interactive = computed(() => store.live)

/**
 * 「开始上课」这个按钮什么时候在。
 *
 * 除了「还没开课」和「上完了」，**还含 `idle`**：会话建好了但一句没讲
 * （点过开始上课、人却刷了新，或者上一堂的空会话被游标捞了回来）。
 * 这种状态下右上角如果只给一个「下课」，这堂课就没有开讲的入口了 ——
 * 舞台上的 ▶ 在 `idle` 时是灰的（`ClassroomStage` 的 `canToggle`），
 * 它给的提示偏偏又是「在右上角点开始上课」。
 */
const canStart = computed(
  () => !sessionId.value || status.value === 'ended' || status.value === 'idle',
)

/** 服务端给的可讲页（时间线）。开课之前它是空的 —— 那时候课还没开出来。 */
const pages = computed(() => (timeline.value?.pages ?? []).map((page) => page.pageNo))

/**
 * 逐页手翻（P3-G3 的降级路）与开课前的预览：**这条路上没有服务端在跟着翻**，
 * 所以页号是本地的。
 *
 * 这与「不许本地推算」不冲突 —— 那条纪律管的是**有服务端在讲的时候**：
 * 那时页面上显示的必须是服务端认定的位置。而推送通道关着的时候服务端
 * 一个事件也发不出来、开课之前更是没有会话，本地翻页是这堂课唯一能做的事。
 */
const localOnly = computed(() => !sessionId.value || store.wsDisabled)
const localNo = ref(0)

/** 课程正文：舞台上渲染的是它（时间线只给位置与元信息）。 */
const coursePages = computed(() => course.value?.pages ?? [])

/** 能翻的页：有服务端时间线就照它翻，否则照课程自己的页翻。 */
const navNos = computed(() =>
  pages.value.length ? pages.value : coursePages.value.map((item) => item.pageNo),
)

const shownNo = computed(() =>
  localOnly.value ? localNo.value || navNos.value[0] || 0 : pageNo.value,
)
const index = computed(() => navNos.value.indexOf(shownNo.value))
const slide = computed(
  () => coursePages.value.find((item) => item.pageNo === shownNo.value) ?? null,
)
const canPrev = computed(() => index.value > 0)
const canNext = computed(() => index.value >= 0 && index.value < navNos.value.length - 1)
const pageCount = computed(
  () => timeline.value?.pageCount || course.value?.pageCount || navNos.value.length,
)

// --- 连接 ---

const socket = useClassroomSocket({
  sessionId: () => sessionId.value,
  cursor: () => ({ pageNo: pageNo.value, beatIdx: store.beatIdx, afterSeq: lastSeq.value }),
  onEvent: (event: ClassroomEvent) => {
    store.applyEvent(event)
  },
  // 进课堂就把最近的几条消息拉回来：WS 只推「此刻之后」的事件，
  // 整堂课的历史走 HTTP（见 §4.2 的 `hello` 口径）。
  onEnter: () => void loadHistory(),
  onResume: () => void loadHistory(),
})

// 通道的状态落进 store 一份：顶栏与面板读的是它（课堂的传输状态也是课堂状态
// 的一部分 —— 断线时字幕不再往前走，这件事界面上得看得见）。
watch(socket.state, (value) => {
  store.connection = value
})

const connected = computed(() => connection.value === 'open')
const reconnecting = computed(() => connection.value === 'reconnecting')

const connectionError = computed(() => socket.error.value || store.connectionError)

const downHint = computed(() => {
  if (socket.fallback.value) return socket.fallback.value
  if (reconnecting.value)
    return `连接中断，正在重连（第 ${socket.attempts.value} 次）—— 课还在上，接上之后会自动对齐。`
  return ''
})

async function loadHistory(): Promise<void> {
  const id = sessionId.value
  if (!id) return
  try {
    const page = await classroomApi.fetchMessages(id, { size: 60 })
    store.applyHistory(page.items)
  } catch {
    // 历史读不出来不影响正在上的课：WS 上的新消息照收，缺的只是进课堂之前的那几条
  }
}

// --- 声音与「这一句讲完了」 ---

const { speaking, speakEnd } = storeToRefs(store)

const player = useBeatPlayer({
  speaking,
  speakEnd,
  claim: (turnId) => store.claimBeatReport(turnId),
  onBeatDone: (beatId) => {
    // 时间线在这里往前走一格。发不出去也没关系：重连之后 `state` 会把位置对齐，
    // 而这一格会在老师重新讲这一句时再报一次。
    socket.send({ type: 'beat_done', beatId })
  },
})

/** 当前这一句在音频清单里的那一条（字级时间戳与时长都在它身上）。 */
const cues = computed<AudioBeat | null>(() => {
  const beatId = speaking.value?.beats?.[0]
  if (!beatId) return null
  return manifest.value?.beats.find((beat) => beat.beatId === beatId) ?? null
})

/** 这门课有没有合成过语音。没有就是纯文字课堂（P2-G3 的降级口径）。 */
const hasAudio = computed(() =>
  Boolean(manifest.value?.available && (manifest.value?.readyCount ?? 0) > 0),
)

const silentReason = computed(() => noVoiceReason(manifest.value?.reason ?? ''))

/**
 * 音频提示条。**只在真的有事要说的时候显示**：
 * 合成的进度、没有声音的原因、离线替身这件事。都好了就整条收起来 ——
 * 一节课中间常挂一条黄条，比不提示更烦人。
 */
const audioNotice = computed(() => {
  const data = manifest.value
  if (!data) return null
  if (!data.available)
    return { theme: 'info' as const, text: silentReason.value || '这节课没有合成语音，讲稿与字幕照常可用。', canNarrate: false }
  if (data.simulated && data.readyCount > 0)
    return { theme: 'warning' as const, text: '当前是离线替身合成的音频（静音），用来验证播放链路；配上真实凭据后声音才是真的。', canNarrate: false }
  if (data.beatCount > 0 && data.readyCount >= data.beatCount) return null
  return {
    theme: 'warning' as const,
    text:
      data.readyCount > 0
        ? `语音合成中：${data.readyCount} / ${data.beatCount} 句已就绪。`
        : '这节课还没有合成语音 —— 合成之后字幕会跟着声音逐词高亮。',
    canNarrate: !data.running,
  }
})

const narrating = ref(false)

async function narrate(): Promise<void> {
  if (!courseId.value) return
  narrating.value = true
  try {
    manifest.value = await api.narrateCourse(courseId.value)
    MessagePlugin.success('已开始合成，进度会显示在这里')
  } catch (error) {
    MessagePlugin.error(describeError(error))
  } finally {
    narrating.value = false
  }
}

async function refreshManifest(): Promise<void> {
  if (!courseId.value) return
  try {
    manifest.value = await api.fetchAudioManifest(courseId.value)
  } catch {
    manifest.value = null // 清单读不出来就是「没有字幕时间戳」，课照上
  }
}

const poll = usePolling(() => void refreshManifest(), 2000)
watch(
  () => manifest.value?.running,
  (running) => {
    if (running) poll.start()
    else poll.stop()
  },
)

// --- 开课 / 恢复 / 下课 ---

/** 开课。**只在真的要点「开始上课」的时候调**（真实的 LLM 调用在后面的每一拍里）。 */
async function start(): Promise<void> {
  if (!courseId.value || starting.value) return
  starting.value = true
  try {
    const started = await classroomApi.startSession({ courseId: courseId.value, mode: 'auto' })
    store.applyStart(started)
    store.courseId = courseId.value
    store.courseTitle = course.value?.title ?? store.courseTitle
    saveCursor({ sessionId: started.sessionId, seq: 0, courseId: courseId.value })
    // 会话行里还有两样开课响应给不出的东西：**我是谁**（举手位次与被点名都按
    // `ownerId` 认）和在线名单。**先读它再建连**：读回来的位置是「刚刚」的，
    // 建连之后 `hello` 会推一份新的 `state` 覆盖上去；反过来的话，晚到的这一份
    // 会把已经推上来的新状态改回旧位置。
    await refreshIdentity(started.sessionId)
    if (started.mode !== 'auto') {
      // 服务端说这堂课只能手翻（推送通道关着）：这正是「降级只能从 mode 认」
      // 的那个信号（见 `useClassroomSocket` 的模块注释）
      store.wsDisabled = true
      socket.disable('这堂课没有推送通道，已切换为逐页手动翻页：翻页看板书，字幕在字幕页')
    } else {
      socket.primeTicket(started.wsToken)
      await socket.open()
      // 连上就开讲。**这一句不能省**：新会话是 `idle`（P3 §2.1 那张表里，
      // 它的退出条件正是「用户点开始上课」），而 `idle → lecture` 在服务端
      // 只有 `play` 这一条路 —— 少了它，建完会话就停在那儿，一句 `speak`
      // 都不会推下来，前端看着就是「点了开始上课，没声音」，得再去点一次
      // 播放器上的 ▶ 才出声。
      play()
    }
  } catch (error) {
    // 撞上「同时在上的课」上限：服务端那句「先结束其中一堂再开新的」得能照做，
    // 所以接着把「正在上的课」那张单子打开 —— 只弹一句话就是死路一条。
    if (error instanceof ApiError && error.code === SESSION_LIMIT_CODE) {
      MessagePlugin.warning(describeError(error))
      void openMySessions()
    } else {
      MessagePlugin.error(describeError(error))
    }
  } finally {
    starting.value = false
  }
}

/**
 * 「开始上课」按下去做什么：手上有会话就开讲，没有（或上完了）才新开一堂。
 *
 * 分成两条路是有原因的。刷新回来时游标会把那条空会话捞回来（`resume`），
 * 那时候再走 `start()` 就会另建一条，原来那条 `idle` 的还挂在账上 ——
 * 每人「同时在上的课」有上限（P3-F5，42901），攒够两条就再也开不出新课了。
 */
function onStart(): void {
  if (!sessionId.value || status.value !== 'idle') {
    void start()
    return
  }
  if (play()) return
  // 通道还没开（刷新回来那一下：会话行先到、连接后到）。`send` 在没开的通道上
  // 是**静默丢掉**的，这一下丢了，用户看到的就是「点了开始上课，没声音」。
  // 盯着连接，开了立刻补发，然后就不再盯了。
  const stop = watch(connection, (value) => {
    if (value !== 'open') return
    stop()
    play()
  })
}

/**
 * 读一次会话行：**我是谁、课叫什么、谁还在线**都在它里面。
 *
 * 读不到不是致命的（课照上，只是举手位次按「我」认不出来）—— 所以这里
 * 只警告不抛出，让调用方接着往下走。
 */
async function refreshIdentity(id: string): Promise<void> {
  try {
    const summary = await classroomApi.fetchSession(id)
    store.courseId = summary.courseId || courseId.value
    store.applySummary(summary)
  } catch (error) {
    MessagePlugin.warning(`读取课堂状态失败：${describeError(error)}`)
  }
}

/** 刷新之后回到同一堂课（P3-A10）：游标在 sessionStorage 里，位置以会话行为准。 */
async function resume(id: string): Promise<void> {
  try {
    // 先把游标放回去再建连：`hello` 里的 `afterSeq` 取自它，于是断线期间漏掉的
    // 那几条会由补发带回来。不还回去的话起点是「此刻」，中间那一段就凭空没了。
    const cursor = loadCursor(courseId.value)
    if (cursor?.sessionId === id) store.setCursor(cursor.seq)

    const summary = await classroomApi.fetchSession(id)
    store.sessionId = id
    store.courseId = summary.courseId || courseId.value
    store.applySummary(summary)
    await socket.open()
  } catch (error) {
    // 恢复不了（课上完了 / 不是我的课）就当没这回事，回到「开始上课」那一步
    clearCursor(courseId.value)
    store.reset()
    MessagePlugin.warning(`没能回到上一堂课：${describeError(error)}`)
  }
}

async function end(): Promise<void> {
  if (!sessionId.value || ending.value) return
  ending.value = true
  try {
    await classroomApi.endSession(sessionId.value, 'user')
  } catch (error) {
    MessagePlugin.error(describeError(error))
  } finally {
    ending.value = false
  }
}

// --- 我正在上的课（P3-F5）---

/** 每人同时在上的课有上限；撞上时服务端回的码（`RateLimitError`）。 */
const SESSION_LIMIT_CODE = 42901

const mySessions = ref<ClassroomSummary[]>([])
const sessionLimit = ref(0)
const sessionsOpen = ref(false)
const sessionsLoading = ref(false)
const endingId = ref('')

/**
 * 「我正在上的课」：把占着名额的那几堂课列出来，就地关掉。
 *
 * 谁需要它：开课时撞上每人上限的人。服务端那时只说一句「先结束其中一堂再开新的」，
 * 而界面上原来没有任何地方能看见、也关不掉「其中一堂」—— 多出来那些通常是之前
 * 点着试出来的空会话（`idle`，一句没讲过），人就卡在「再也开不出新课」上了。
 * 所以「开始上课」一旦收到 42901，除了弹出那句话，还要把这张单子打开。
 */
async function openMySessions(): Promise<void> {
  sessionsOpen.value = true
  await loadMySessions()
}

async function loadMySessions(): Promise<void> {
  sessionsLoading.value = true
  try {
    const page = await classroomApi.listSessions()
    mySessions.value = page.items
    sessionLimit.value = page.limit
  } catch (error) {
    MessagePlugin.warning(`读取正在上的课失败：${describeError(error)}`)
  } finally {
    sessionsLoading.value = false
  }
}

/**
 * 在单子里关掉一堂：**不用先进去**，这就是页面右上角那个「下课」，只是对象不是
 * 当前这堂。当前这堂被关掉时不必手动改 store —— 服务端会推一条 `state` 过来，
 * 与「下当前这堂课」走的是同一条（两条路改同一个状态机，必然对不上）。
 */
async function endFromList(id: string): Promise<void> {
  if (endingId.value) return
  endingId.value = id
  try {
    await classroomApi.endSession(id, 'user')
    MessagePlugin.success('已结束，名额腾出来了')
    await loadMySessions()
  } catch (error) {
    MessagePlugin.error(describeError(error))
  } finally {
    endingId.value = ''
  }
}

/** 单子里的状态中文。认不出来的原样显示，别糊成「未知」。 */
const statusText = (value: string): string =>
  CLASSROOM_STATUS_LABELS[value as keyof typeof CLASSROOM_STATUS_LABELS] ?? value

// --- 上行 ---

function seek(target: number): void {
  if (!navNos.value.includes(target)) return
  // 手翻的那条路上没有服务端在听，直接挪本地页号
  if (localOnly.value) {
    localNo.value = target
    return
  }
  socket.send({ type: 'seek', pageNo: target })
}

function go(offset: number): void {
  const target = navNos.value[index.value + offset]
  if (target) seek(target)
}

/**
 * 播与停。
 *
 * **不看本地播放器在不在响**：有没有声音与课走不走是两件事 —— 一节没有合成
 * 语音的课照样在讲，只是没声音。所以这一对动作只把「继续」和「停住」发上去，
 * 由服务端的状态机说了算（`_on_play` / `_on_pause`）。
 */
function play(): boolean {
  // 返回值是「这一下有没有发出去」：通道没开时 `send` 会静默丢掉，而
  // 「开讲」这一下丢掉就是没声音，调用方得知道（见 `onStart`）。
  return socket.send({ type: 'play' })
}

function pause(): void {
  socket.send({ type: 'pause' })
}

function setSpeed(value: number): void {
  socket.send({ type: 'speed', value })
}

function toggleHand(): void {
  if (!interactive.value) return
  socket.send({ type: 'hand', action: store.myHandPosition > 0 ? 'lower' : 'raise' })
}

/**
 * 发言的两条路（`_on_ask` / `_on_chat`）。
 *
 * **被点名时走 `ask`**：那是「我提问、老师答」这条规则的入口，老师必答。
 * 平时走 `chat`：普通发言进讨论区，**引用老师的那一条**才算点名老师作答
 * （服务端认 `target === 'teacher'`）。两条都是课堂自己的消息，都会落进
 * 这节课的记录里 —— 这也是为什么不走 P2 的实时语音通道。
 */
function submitAsk(payload: { text: string; mode: 'voice' | 'text'; quoteMsgId: string }): void {
  const text = payload.text.trim()
  if (!text) return
  if (!connected.value) {
    MessagePlugin.warning('与课堂的连接还没建起来，这句话没发出去')
    return
  }
  const quoted = payload.quoteMsgId
    ? store.messages.find((item) => item.id === payload.quoteMsgId)
    : undefined
  const targetTeacher = store.iAmCalled || payload.mode === 'voice' || quoted?.speakerKind === 'teacher'
  const sent = targetTeacher
    ? socket.send({ type: 'ask', text, quoteMsgId: payload.quoteMsgId })
    : socket.send({ type: 'chat', text, quoteMsgId: payload.quoteMsgId, target: '' })
  if (!sent) MessagePlugin.warning('这句话没发出去，稍后再试')
}

/**
 * 随堂测验的弹框开着吗。
 *
 * **题一到就自己弹出来**（`watch` 那一条），答完之后由学生自己收 ——
 * 判定与解析要留在屏幕上给人看完，不能答完就收。
 */
const quizClosed = ref(false)
const showQuiz = computed(() => Boolean(store.quiz) && !quizClosed.value)

watch(
  () => store.quiz,
  (value) => {
    if (value) quizClosed.value = false
  },
)

function closeQuiz(): void {
  quizClosed.value = true
}

/**
 * 跳过这道题：课堂停在 `quiz_wait` 等作答，再报一次 `beat_done` 就是「跳过」
 * （见 `runtime._on_beat_done`）。报的是空 `beatId` —— 服务端把认不出来的
 * 一律当「现在这一拍」，这正是我们要的。
 */
function skipQuiz(): void {
  socket.send({ type: 'beat_done', beatId: '' })
  closeQuiz()
}

async function submitQuiz(option: string): Promise<void> {
  if (!sessionId.value || quizSubmitting.value) return
  quizSubmitting.value = true
  const started = Date.now()
  try {
    const result = await classroomApi.submitQuiz(sessionId.value, {
      option,
      responseMs: Date.now() - started,
    })
    // 回执就是那条 `quiz_result` 事件（带 `seq`）—— 走同一条入口落进 store，
    // 于是 WS 上广播回来的同一条会被 `seq` 去重掉，不会判两次
    store.applyEvent(result as unknown as ClassroomEvent)
  } catch (error) {
    MessagePlugin.error(describeError(error))
  } finally {
    quizSubmitting.value = false
  }
}

function onExport(value: string): void {
  const label = value === 'share' ? '分享课堂链接' : `导出 ${value.toUpperCase()}`
  MessagePlugin.info(`${label}在 P4 阶段接入（导出与分享）`)
}

// --- 沉浸模式与快捷键 ---

function toggleImmersive(): void {
  immersive.value = !immersive.value
}

/** 在输入框里打字时空格是空格 —— 这个判断在 P2 就写错过一次。 */
function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  if (!element || !element.tagName) return false
  const tag = element.tagName.toLowerCase()
  return tag === 'input' || tag === 'textarea' || tag === 'select' || element.isContentEditable
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.metaKey || event.ctrlKey || event.altKey) return
  if (event.key === 'Escape') {
    immersive.value = false
    return
  }
  if (isTypingTarget(event.target)) return
  if (event.code === 'Space' && !event.repeat) {
    event.preventDefault() // 空格默认会滚动页面
    toggleHand()
    return
  }
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    go(-1)
    return
  }
  if (event.key === 'ArrowRight') {
    event.preventDefault()
    go(1)
  }
}

// --- 加载 ---

const readyCourses = computed(() =>
  candidates.value.filter((item) => item.status === 'ready' && item.readyPages > 0),
)

async function loadCandidates(): Promise<void> {
  try {
    const list = await api.fetchCourses({ status: 'ready', size: 20 })
    candidates.value = list.items
  } catch {
    candidates.value = []
  }
}

function pickCourse(id: string): void {
  void router.replace({ path: '/classroom', query: { course: id } })
}

async function load(id: string): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    course.value = await api.fetchCourse(id, { withPages: true })
    await refreshManifest()
  } catch (error) {
    course.value = null
    loadError.value = describeError(error)
  } finally {
    loading.value = false
  }
}

watch(
  courseId,
  (id) => {
    if (id) {
      void load(id)
      return
    }
    course.value = null
    manifest.value = null
    loadError.value = ''
    void loadCandidates()
  },
  { immediate: true },
)

/**
 * 刷新恢复：先进来的那一次问「还是这堂课吗」。
 *
 * 两个来源：地址栏上的 `?session=`（从别处指过来）与 sessionStorage 里的游标
 * （自己刷新）。**都不用「courseId 有没有课」来判断** —— 一堂课上到一半刷新，
 * 该做的是接着上，不是又开一堂。
 */
onMounted(async () => {
  void settings.loadRoles()
  window.addEventListener('keydown', onKeyDown)
  if (sessionQuery.value) {
    await resume(sessionQuery.value)
    return
  }
  const cursor = courseId.value ? loadCursor(courseId.value) : null
  if (cursor?.sessionId) await resume(cursor.sessionId)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown)
  player.stop()
  socket.close()
  poll.stop()
})

/** 游标落盘（每次 `seq` 往前走都记一笔）——刷新之后靠它认出「还是这堂课」。 */
watch(lastSeq, (seq) => {
  if (!sessionId.value || !courseId.value) return
  saveCursor({ sessionId: sessionId.value, seq, courseId: courseId.value })
})

/** 服务端下发的私有 `error`：说一句，但**不改课堂状态**（它只是一条通知）。 */
watch(lastError, (message) => {
  if (message) MessagePlugin.error(message)
})

/**
 * 下课 → 课堂记录（P3-6）。
 *
 * 下课可能是老师讲完了（服务端推 `ended`），也可能是这边按的「下课」。
 * 两条路都在这里收口：清掉游标（这堂课不能再续了），跳到记录页看回顾。
 */
watch(status, (value) => {
  if (value !== 'ended' || !sessionId.value) return
  clearCursor(courseId.value)
  socket.close()
  void router.push({ path: '/classroom/record', query: { session: sessionId.value } })
})

const headerTitle = computed(() => store.courseTitle || course.value?.title || '课堂')
const onlineCount = computed(() => presence.value.online)
const handLabel = computed(() =>
  store.myHandPosition > 0 ? `已举手（第 ${store.myHandPosition} 位）` : '举手',
)
</script>

<template>
  <div class="cls" :class="{ 'is-immersive': immersive }">
    <header class="cls-header">
      <span class="back" title="返回首页" @click="router.push('/')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M15 5l-7 7 7 7" />
        </svg>
      </span>
      <div class="cls-header__info">
        <div class="cls-header__title">{{ headerTitle }}</div>
        <div class="cls-header__meta">
          <!-- 「课开出来了但还没开讲」（`idle`）与「还没开课」（没有会话）是两件事：
               前者可以举手答题了吗——不行；但它已经是一堂课了，所以标签不一样 -->
          <t-tag v-if="sessionId" variant="light" theme="primary">
            {{ CLASSROOM_STATUS_LABELS[status] }}
          </t-tag>
          <t-tag v-else variant="light">尚未开课</t-tag>
          <t-tag v-if="sessionId" variant="light" :title="`${onlineCount} 人正在这堂课里`">
            在线 {{ onlineCount }}
          </t-tag>
          <t-tag v-if="store.wsDisabled" variant="light" theme="warning">手动翻页</t-tag>
          <t-tag v-if="store.mode === 'manual' && !store.wsDisabled" variant="light">
            手动模式
          </t-tag>
        </div>
      </div>
      <span class="spacer" />
      <!--
        入口常驻：卡在「先结束其中一堂」的人，第一反应就是来顶上找那名额在哪儿。
        没在上的课就显示一行「没有正在上的课」，比按钮时有时无好找。
      -->
      <t-button variant="outline" title="我正在上的课，以及怎么把占着名额的关掉" @click="openMySessions">
        正在上的课
      </t-button>
      <t-button
        v-if="sessionId && status !== 'ended'"
        :theme="store.myHandPosition > 0 ? 'warning' : 'default'"
        :disabled="!interactive"
        :title="interactive ? '举手（也可以按空格）' : '课堂还没开始'"
        @click="toggleHand"
      >
        <template #icon>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path
              d="M7 11V5.5a1.5 1.5 0 0 1 3 0V10m0-4.5v-1a1.5 1.5 0 0 1 3 0V10m0-4.5a1.5 1.5 0 0 1 3 0V12m0-3a1.5 1.5 0 0 1 3 0v5a6 6 0 0 1-6 6h-1.4a6 6 0 0 1-4.8-2.4L4 15.6a1.6 1.6 0 0 1 2.6-1.9L7 14.5"
            />
          </svg>
        </template>
        {{ handLabel }}
      </t-button>
      <t-button
        v-if="canStart"
        theme="primary"
        :loading="starting"
        :disabled="!courseId || !course"
        @click="onStart"
      >
        开始上课
      </t-button>
      <!--
        闲置的会话也留一个「下课」：开讲之前反悔的那条得能自己收掉，
        不然它一直占着「同时在上的课」的名额。
      -->
      <t-button v-if="sessionId && status !== 'ended'" :loading="ending" @click="end">
        下课
      </t-button>
      <t-button shape="square" variant="outline" :title="immersive ? '退出沉浸模式（Esc）' : '沉浸模式'" @click="toggleImmersive">
        <template #icon>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
          </svg>
        </template>
      </t-button>
      <t-dropdown
        :options="[
          { value: 'pptx', content: '导出 PPTX' },
          { value: 'html', content: '导出 HTML' },
          { value: 'pdf', content: '导出 PDF' },
          { value: 'share', content: '分享课堂链接', divider: true },
        ]"
        trigger="click"
        @click="onExport($event as string)"
      >
        <t-button variant="outline">
          <template #icon>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M12 3v12M7 10l5 5 5-5" />
              <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
            </svg>
          </template>
          导出课件
        </t-button>
      </t-dropdown>
      <t-button shape="square" variant="outline" title="设置" @click="router.push('/settings')">
        <template #icon>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <circle cx="12" cy="12" r="3" />
            <path
              d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.51 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1Z"
            />
          </svg>
        </template>
      </t-button>
    </header>

    <!-- 连接状态：断了就说清「正在重连」，别让人对着一动不动的课堂猜 -->
    <div v-if="downHint || connectionError" class="cls-notice">
      <t-alert :theme="connectionError ? 'error' : 'info'">
        <template #message>{{ connectionError || downHint }}</template>
      </t-alert>
    </div>

    <div v-if="course && audioNotice" class="cls-notice">
      <t-alert :theme="audioNotice.theme">
        <template #message>
          <div class="cls-notice__row">
            <span>{{ audioNotice.text }}</span>
            <t-button
              v-if="audioNotice.canNarrate"
              size="small"
              theme="primary"
              :loading="narrating"
              @click="narrate"
            >
              合成语音
            </t-button>
          </div>
        </template>
      </t-alert>
    </div>

    <div class="cls-body">
      <!--
        随堂测验走**左侧弹框**（F3-8）：题面一到就滑进来，答完（或跳过）之后收起来。

        它也不再占舞台那一列的**高度** —— 原来题卡挤在字幕和播放条中间，一弹出来
        幻灯片就得从 960 缩到 700 才排得下（`.stage-wrap` 要给它留 180px）。
        现在改为占左边一栏、舞台自己让位：幻灯片随之等比缩放，图不会被盖住。
      -->
      <Transition name="quiz-panel">
        <section v-if="showQuiz" class="cls-quiz" role="dialog" aria-label="随堂测验">
          <button
            class="cls-quiz__close"
            :disabled="!store.quizResult"
            :title="store.quizResult ? '收起（课堂照常继续）' : '答完这道题就能收起来'"
            @click="closeQuiz"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>

          <QuizCard
            class="cls-quiz__card"
            :quiz="store.quiz"
            :result="store.quizResult"
            :submitting="quizSubmitting"
            :reading="speaking?.kind === 'lecture' ? speaking.text : ''"
            @submit="submitQuiz"
          />

          <!--
            没答之前给一条退路：`quiz_wait` 里再报一次 `beat_done` 就是「跳过这道题」
            （见 `runtime._on_beat_done`）。少了它，不想答的人只能干看着课堂停在这儿。
          -->
          <button
            v-if="store.quiz && !store.quizResult"
            class="cls-quiz__skip"
            title="跳过之后这一页不再问，课堂继续往下讲"
            @click="skipQuiz"
          >
            跳过这道题
          </button>
        </section>
      </Transition>

      <ClassroomStage
        :page="slide"
        :course-title="store.courseTitle || course?.title || ''"
        :page-count="pageCount"
        :can-prev="canPrev"
        :can-next="canNext"
        :loading="loading"
        :empty-title="loadError ? '这门课没读出来' : '还没有可讲授的课程'"
        :empty-text="
          loadError ||
          (courseId
            ? '这门课还没有生成好的页面 —— 回工作台把它生成完，再回来看。'
            : '从下面选一门已生成的课，或者回工作台生成一门。')
        "
        :status="status"
        :speaking="speaking"
        :subtitle="store.currentSubtitle?.text ?? ''"
        :speaker-name="speaking?.speaker?.name ?? ''"
        :playing="player.playing.value"
        :position-ms="player.positionMs.value"
        :cues="cues"
        :page-no="shownNo"
        :elapsed-ms="store.elapsedMs"
        :total-ms="store.totalMs"
        :speed="store.speed"
        :has-audio="hasAudio"
        :silent-reason="silentReason"
        @prev="go(-1)"
        @next="go(1)"
        @play="play"
        @pause="pause"
        @seek="seek"
        @speed="setSpeed"
      />

      <ClassroomPanel
        v-if="!immersive"
        :connected="connected"
        :interactive="interactive"
        @jump="seek"
        @hand="(action) => socket.send({ type: 'hand', action })"
        @ask="submitAsk"
      />
    </div>

    <!-- 没选课：先挑一门（有已生成页的课才上得起来） -->
    <div v-if="!courseId && !loadError" class="cls-picker">
      <h3>选一门课，开始上课</h3>
      <p class="cls-picker__hint">
        课堂要有讲稿与页面才能跑：下面是已经生成好的课。
      </p>
      <div v-if="readyCourses.length" class="cls-picker__list">
        <button v-for="item in readyCourses" :key="item.id" class="pick" @click="pickCourse(item.id)">
          <span class="pick__title">{{ item.title }}</span>
          <span class="pick__meta">{{ item.readyPages }} / {{ item.pageCount }} 页 · 约 {{ item.durationMin }} 分钟</span>
        </button>
      </div>
      <t-empty v-else description="还没有生成好的课 —— 去工作台生成一门，再回来上课。" />
    </div>

    <!--
      正在上的课（P3-F5）。每人同时在上的课有上限（默认 2 堂），攒够之后
      「开始上课」会被服务端按 42901 挡回来，只说「先结束其中一堂再开新的」——
      这张单子就是「其中一堂」在哪，顺手就地关掉。
    -->
    <t-dialog v-model:visible="sessionsOpen" header="正在上的课" :footer="false" width="520px">
      <p class="cls-sessions__hint">
        每人同时在上的课最多 {{ sessionLimit || '—' }} 堂。上面那些占着名额又没在上的
        （多半是之前点着试出来的），在这里结束掉就能开新的。
      </p>
      <div v-if="sessionsLoading" class="cls-sessions__empty">读取中……</div>
      <div v-else-if="!mySessions.length" class="cls-sessions__empty">
        没有正在上的课，直接开新的就行。
      </div>
      <ul v-else class="cls-sessions">
        <li v-for="row in mySessions" :key="row.id" class="cls-sessions__row">
          <div class="cls-sessions__main">
            <span class="cls-sessions__title">{{ row.courseTitle || '（课已删除）' }}</span>
            <span class="cls-sessions__meta">
              第 {{ row.pageNo || 1 }} 页 · {{ statusText(row.status) }}
              <template v-if="row.id === sessionId"> · 就是当前这堂</template>
            </span>
          </div>
          <t-button
            size="small"
            variant="outline"
            :loading="endingId === row.id"
            @click="endFromList(row.id)"
          >
            结束
          </t-button>
        </li>
      </ul>
    </t-dialog>
  </div>
</template>
<style scoped src="../styles/views/ClassroomView.css"></style>
