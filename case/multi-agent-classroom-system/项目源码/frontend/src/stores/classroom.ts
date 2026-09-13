/**
 * 课堂 Store（P3 §6 的「单一课堂 Store」）。
 *
 * **一条纪律：除了 `applyEvent`，没有第二个入口能改课堂状态。**
 *
 * 为什么把这句话写死：课堂有两份状态（服务端一份、这里一份），它们迟早会分叉。
 * 分叉的时候如果前端还在「乐观地」自己往前推——点了下一页就先把 pageNo 加一、
 * 举手就先把按钮变绿——那么分叉的表现就不是「卡住」，而是「显示的是第 5 页、
 * 老师讲的是第 4 页」，而且**看不出谁错了**。所以：
 *
 * - 翻页发出 `seek` 之后什么都不做，等服务端把 `state` 推回来；
 * - 举手发出 `hand` 之后什么都不做，等 `hand_queue` 推回来；
 * - 播放器的进度、字幕、板书同理。
 *
 * 代价是每次操作要等一个来回（本地几十毫秒，够快）；换来的是**界面上看到的
 * 一定就是服务端认定的那一份**。P3-A13（多标签页互相不覆盖）靠的也是这一条：
 * 两个标签页都在等同一份服务端状态，谁也没法用自己的本地版本覆盖对方。
 *
 * 三处看起来是例外、其实不是：`applySummary` / `applyHistory` / `applyRecord`
 * 读的是 **HTTP 上的服务端数据**（刷新恢复、翻历史消息、回看记录），
 * 它们只是把同一份服务端事实从另一条路搬进来，不是本地推算出来的。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type {
  BoardStroke,
  ClassroomEvent,
  ClassroomMessage,
  ClassroomPresence,
  ClassroomQuiz,
  ClassroomRecord,
  ClassroomStart,
  ClassroomStatus,
  ClassroomSummary,
  ClassroomTimeline,
  HandItem,
  QuizResult,
  SpeakPayload,
  TimelinePage,
} from '@/types/classroom'

/** 连接的状态。`reconnecting` 是「断过，正在按退避重试」——顶栏灰条靠它显示。 */
export type ConnectionState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'

/** 一条字幕。`subtitle` 事件一条一条来，攒成字幕 Tab 的历史流。 */
export interface SubtitleLine {
  beatId: string
  text: string
  pageNo: number
  at: number
}

/**
 * 一条发言的收尾（`speak_end`）。`preempted` 为真时是被打断的，不算说完。
 *
 * `kind` 是**已经结束的那一轮**的发言类型（`lecture` / `answer` / …）。
 * `speak_end` 这个事件本身不带它（见 §4.2 的载荷），所以只能在这一刻
 * 从还挂在 `speaking` 上的那条发言抄下来 —— 之后 `speaking` 就清空了，
 * 页面再也无从知道刚才结束的是「讲稿」还是「答疑」，而这两件事收尾之后
 * 要做的事不一样（讲稿要推进时间线，答疑要给时间线解冻）。
 */
export interface SpeakEnd {
  turnId: string
  preempted: boolean
  kind: string
  at: number
}

/** 当前正在说/刚说过的那一条（讨论区顶上那个「正在输入…」按它显示）。 */
export interface TypingState {
  speaker: { code: string; name: string }
  pageNo: number
}

export const useClassroomStore = defineStore('classroom', () => {
  // --- 会话 ---
  const sessionId = ref('')
  const courseId = ref('')
  const courseTitle = ref('')
  const ownerId = ref('')
  const mode = ref<'auto' | 'manual'>('auto')
  const status = ref<ClassroomStatus>('idle')
  const pageNo = ref(0)
  const beatIdx = ref(0)
  const elapsedMs = ref(0)
  const totalMs = ref(0)
  const speed = ref(1)
  const timeline = ref<ClassroomTimeline | null>(null)

  // --- 事件流 ---
  /** 已经收到的最大 `seq`。重连时把它当 `afterSeq`，服务端从它之后补发。 */
  const lastSeq = ref(0)
  const connection = ref<ConnectionState>('idle')
  const connectionError = ref('')
  /** 服务端下发的私有 `error`（只发给我一个人的那些）里最后一条，用来提示。 */
  const lastError = ref('')
  /** 推送通道被关掉（`CLASSROOM_WS=false`）时的降级标记（P3-G3）。 */
  const wsDisabled = ref(false)

  // --- 直播内容 ---
  const speaking = ref<SpeakPayload | null>(null)
  const speakEnd = ref<SpeakEnd | null>(null)
  const typing = ref<TypingState | null>(null)
  const subtitles = ref<SubtitleLine[]>([])
  const messages = ref<ClassroomMessage[]>([])
  const handQueue = ref<HandItem[]>([])
  const called = ref<HandItem | null>(null)
  /** 页号 → 这一页的板书。服务端每次给的是**整页**，所以直接换掉。 */
  const boards = ref<Record<number, BoardStroke[]>>({})
  const quiz = ref<ClassroomQuiz | null>(null)
  const quizResult = ref<QuizResult | null>(null)
  const presence = ref<ClassroomPresence>({
    online: 0,
    members: [],
    aiMembers: [],
  })

  // 去重用的索引。**不是响应式的**：它们只是「见过没有」，界面不读它们。
  // 放进响应式状态里会让每条消息触发两次无关的重算。
  let seenMessages = new Set<string>()
  let seenSubtitles = new Set<string>()
  /** 已经报过 `beat_done` 的 turn。同一个 beat 被重新讲是一轮新的 turnId，仍可再报。 */
  const reportedBeats = new Set<string>()

  // --- 派生 ---

  const pages = computed<TimelinePage[]>(() => timeline.value?.pages ?? [])

  const currentPage = computed<TimelinePage | null>(
    () => pages.value.find((page) => page.pageNo === pageNo.value) ?? null,
  )

  const pageCount = computed(() => timeline.value?.pageCount ?? pages.value.length)

  /** 当前这一页的板书（课上一共有多少笔，白板 Tab 就画多少笔）。 */
  const currentStrokes = computed<BoardStroke[]>(() => boards.value[pageNo.value] ?? [])

  /** 最新一条字幕 —— 舞台下方那一条。 */
  const currentSubtitle = computed<SubtitleLine | null>(
    () => subtitles.value[subtitles.value.length - 1] ?? null,
  )

  /** 讲稿字幕（讨论区只显示有 beat 的那些之外的）。 */
  const discussion = computed(() =>
    messages.value.filter((item) => item.type !== 'lecture' || item.speakerKind !== 'teacher'),
  )

  /**
   * 我在举手队列里排第几（从 1 起，0 = 没举）。
   *
   * 「我」按 `ownerId` 认：MVP 里开课的人就是听课的人（票据签给谁，谁就是这条
   * 连接的用户），所以这个判据是准的。真要做多人在线，得让服务端在 `hand_queue`
   * 里带上「这一条是你」——那时候这里换成读那个字段。
   */
  const myHandPosition = computed(() => {
    const index = handQueue.value.findIndex((item) => item.userId === ownerId.value)
    return index >= 0 ? index + 1 : 0
  })

  /** 被点到名的是不是我 —— 「弹出提问条并自动开始录音」看它。 */
  const iAmCalled = computed(
    () => Boolean(called.value) && called.value?.userId === ownerId.value,
  )

  /** 课上到第几页 / 总共几页（进度条与大纲跳转都用它）。 */
  const progress = computed(() => {
    if (totalMs.value <= 0) return 0
    return Math.min(100, Math.max(0, (elapsedMs.value / totalMs.value) * 100))
  })

  const live = computed(() => status.value !== 'idle' && status.value !== 'ended')
  const ended = computed(() => status.value === 'ended')

  // --- 写入：只由事件驱动 ---

  /**
   * 收下一条下行事件。**这是唯一改课堂状态的入口。**
   *
   * 返回「这条事件有没有被吃进去」：`false` 表示是重复/迟到的（`seq` 不比已有的
   * 大），调用方据此跳过副作用（比如重新播放音频）。
   */
  function applyEvent(event: ClassroomEvent): boolean {
    const seq = (event as { seq?: number }).seq
    // `error` 与 `ping` 是**每连接私有**帧，不带 `seq`（见 P3 §4.2）——
    // 它们不参与去重，也不能把游标带偏（带偏了此后补发就一直对不上账）
    if (typeof seq === 'number') {
      if (seq <= lastSeq.value) return false
      lastSeq.value = seq
    }

    switch (event.type) {
      case 'state':
        applyState(event)
        break
      case 'speak': {
        const turn = event as unknown as SpeakPayload
        speaking.value = { ...turn }
        if (typing.value?.speaker.code === turn.speaker.code) typing.value = null
        break
      }
      case 'speak_end': {
        const ending = speaking.value
        speakEnd.value = {
          turnId: event.turnId,
          preempted: Boolean(event.preempted),
          kind: ending?.turnId === event.turnId ? ending.kind : '',
          at: Date.now(),
        }
        if (ending?.turnId === event.turnId) speaking.value = null
        typing.value = null
        break
      }
      case 'typing':
        typing.value = { speaker: event.speaker, pageNo: event.pageNo }
        break
      case 'subtitle':
        pushSubtitle(event.beatId, event.text, event.pageNo)
        break
      case 'message':
        pushMessage(event.msg)
        break
      case 'hand_queue':
        handQueue.value = event.queue
        called.value = event.called
        break
      case 'board':
        boards.value = { ...boards.value, [event.pageNo]: event.strokes }
        break
      case 'quiz':
        quiz.value = { ...(event as unknown as ClassroomQuiz) }
        // 换题就清掉上一题的判定：留着的话新题一上来就显示「回答正确」
        quizResult.value = null
        break
      case 'quiz_result':
        quizResult.value = {
          pageNo: event.pageNo,
          correct: event.correct,
          option: event.option,
          answer: event.answer,
          explain: event.explain,
          branch: event.branch,
        }
        break
      case 'presence':
        presence.value = {
          online: event.online,
          members: event.members,
          // 旧版服务端不发 aiMembers：按空数组收，名单少一行也不该让页面崩
          aiMembers: event.aiMembers ?? [],
        }
        break
      case 'error':
        lastError.value = event.message
        break
      default:
        // 未知类型静默忽略（P3-B3 的向前兼容）：新版本的服务端多发一种事件，
        // 旧版本的页面不该因此崩掉
        break
    }
    return true
  }

  function applyState(payload: {
    status: ClassroomStatus
    pageNo: number
    beatIdx: number
    elapsedMs: number
    totalMs: number
    speed: number
  }): void {
    status.value = payload.status
    pageNo.value = payload.pageNo
    beatIdx.value = payload.beatIdx
    elapsedMs.value = payload.elapsedMs
    totalMs.value = payload.totalMs
    speed.value = payload.speed
    if (payload.status === 'ended') speaking.value = null
  }

  function pushSubtitle(beatId: string, text: string, page: number): void {
    if (!beatId || seenSubtitles.has(beatId)) return
    seenSubtitles.add(beatId)
    subtitles.value = [...subtitles.value, { beatId, text, pageNo: page, at: Date.now() }]
  }

  /**
   * 收一条消息。**按 `id` 去重**（P3-A11 的「无重复消息」）。
   *
   * 去重不能只靠 `seq`：断线期间漏掉的那几条由补发带回来，而「补发」与
   * 「重连时重新播一遍的当前发言」是两条不同的路，同一条消息可能从任一条到。
   */
  function pushMessage(message: ClassroomMessage): void {
    if (!message?.id || seenMessages.has(message.id)) return
    seenMessages.add(message.id)
    // 讲稿消息按时间线位置（`ts`）落位，不是按到达顺序：补发回来的那几条
    // 会晚到，直接 push 到末尾就排错了
    const next = [...messages.value, message]
    next.sort((a, b) => (a.ts === b.ts ? a.id.localeCompare(b.id) : a.ts < b.ts ? -1 : 1))
    messages.value = next
    if (message.beatId) pushSubtitle(message.beatId, message.text, message.pageNo ?? 0)
    // 消息落地了，「正在输入…」就该收起来。**这条是给静默发言用的**：
    // 讨论区里不点名老师的发言只发 `message` 不发 `speak`（见 `_on_chat`），
    // 只靠 `speak` 清的话，那一条的「正在输入」会一直挂在那儿。
    if (typing.value?.speaker.code === message.speaker) typing.value = null
  }

  /** `POST /sessions` 的响应：开课那一步把会话与时间线一次装好。 */
  function applyStart(payload: ClassroomStart): void {
    reset()
    sessionId.value = payload.sessionId
    mode.value = payload.mode
    status.value = payload.status
    timeline.value = payload.timeline
    totalMs.value = payload.timeline.totalMs
  }

  /** `GET /sessions/{id}`：刷新之后先问这一条，把「现在讲到哪」拿回来。 */
  function applySummary(payload: ClassroomSummary): void {
    courseId.value = payload.courseId || courseId.value
    courseTitle.value = payload.courseTitle || courseTitle.value
    ownerId.value = payload.ownerId || ownerId.value
    mode.value = payload.mode
    applyState(payload)
    presence.value = {
      online: payload.presence.online,
      members: payload.presence.members,
      aiMembers: payload.presence.aiMembers ?? [],
    }
  }

  /** `GET /messages`：历史消息走 HTTP，不走 WS（整堂课的历史不由 WS 重放）。 */
  function applyHistory(items: ClassroomMessage[]): void {
    for (const item of items) pushMessage(item)
  }

  /**
   * `GET /board/{pageNo}`：白板 Tab 翻到别页时补读那一页的板书。
   *
   * 与 `applyHistory` 同一条理由：这是**同一份服务端数据**从另一条路进来
   * （WS 只在课上推当前这一页，翻看旧页要自己问一次），不是本地推算。
   */
  function applyBoard(pageNo: number, strokes: BoardStroke[]): void {
    boards.value = { ...boards.value, [pageNo]: strokes }
  }

  /** `GET /record`：记录页那一份只读投影。 */
  function applyRecord(record: ClassroomRecord): void {
    courseTitle.value = record.courseTitle || courseTitle.value
    ownerId.value = record.session.ownerId || ownerId.value
  }

  /** 重连之前把游标取出来（刷新之后从 sessionStorage 恢复，见 `loadCursor`）。 */
  function setCursor(seq: number): void {
    if (seq > lastSeq.value) lastSeq.value = seq
  }

  /**
   * 这一轮发言要不要为它报一次 `beat_done`。
   *
   * **一个 turn 只报一次**（不管是音频播完还是 `speak_end` 先到）——
   * 报两次会让时间线多走一格，而那一格是凭空跳过去的，没有对应的讲解。
   * 去重按 `turnId`：同一个 beat 被重新讲是一轮新的 turnId，仍然可以再报
   * （被打断之后重讲，就该重新推进）。
   */
  function claimBeatReport(turnId: string): boolean {
    if (!turnId || reportedBeats.has(turnId)) return false
    reportedBeats.add(turnId)
    return true
  }

  function reset(): void {
    sessionId.value = ''
    courseId.value = ''
    courseTitle.value = ''
    ownerId.value = ''
    mode.value = 'auto'
    status.value = 'idle'
    pageNo.value = 0
    beatIdx.value = 0
    elapsedMs.value = 0
    totalMs.value = 0
    speed.value = 1
    timeline.value = null
    lastSeq.value = 0
    connection.value = 'idle'
    connectionError.value = ''
    lastError.value = ''
    speaking.value = null
    speakEnd.value = null
    typing.value = null
    subtitles.value = []
    messages.value = []
    handQueue.value = []
    called.value = null
    boards.value = {}
    quiz.value = null
    quizResult.value = null
    presence.value = { online: 0, members: [], aiMembers: [] }
    seenMessages = new Set()
    seenSubtitles = new Set()
    reportedBeats.clear()
  }

  return {
    // 会话
    sessionId,
    courseId,
    courseTitle,
    ownerId,
    mode,
    status,
    pageNo,
    beatIdx,
    elapsedMs,
    totalMs,
    speed,
    timeline,
    // 事件流
    lastSeq,
    connection,
    connectionError,
    lastError,
    wsDisabled,
    // 直播内容
    speaking,
    speakEnd,
    typing,
    subtitles,
    messages,
    handQueue,
    called,
    boards,
    quiz,
    quizResult,
    presence,
    // 派生
    pages,
    currentPage,
    pageCount,
    currentStrokes,
    currentSubtitle,
    discussion,
    myHandPosition,
    iAmCalled,
    progress,
    live,
    ended,
    // 写入
    applyEvent,
    applyStart,
    applySummary,
    applyHistory,
    applyBoard,
    applyRecord,
    setCursor,
    claimBeatReport,
    reset,
  }
})

/** 游标与「这是哪堂课」落在 sessionStorage 里：**每个标签页一份**。 */
const CURSOR_PREFIX = 'eduagentx.classroom.'

export interface StoredCursor {
  sessionId: string
  seq: number
  courseId: string
}

export function saveCursor(cursor: StoredCursor): void {
  try {
    window.sessionStorage.setItem(CURSOR_PREFIX + cursor.courseId, JSON.stringify(cursor))
  } catch {
    // 隐私模式下 sessionStorage 可能直接抛。刷新恢复是锦上添花，
    // 不该让它把正在上的课弄崩 —— 没有游标时退到「停当前 beat，按播放继续」。
  }
}

export function loadCursor(courseId: string): StoredCursor | null {
  try {
    const raw = window.sessionStorage.getItem(CURSOR_PREFIX + courseId)
    return raw ? (JSON.parse(raw) as StoredCursor) : null
  } catch {
    return null
  }
}

export function clearCursor(courseId: string): void {
  try {
    window.sessionStorage.removeItem(CURSOR_PREFIX + courseId)
  } catch {
    // 同上：清不掉就算了，下次覆盖写会盖掉它
  }
}
