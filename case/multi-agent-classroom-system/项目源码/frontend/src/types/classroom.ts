/**
 * 课堂运行时的 TS 类型（P3 §4.1 / §4.2）。
 *
 * 与 `types/api.ts` 分开一份，理由只有一个：**课堂的事件流是另一套契约**。
 * HTTP 那一半（会话、时间线、记录）确实还是「请求—响应」，但 WS 那一半是
 * 「一个下行 dict 按 `type` 分叉」—— 十一种事件共用一个信封，各自带不同的字段。
 * 塞进 api.ts 会让那个文件里一半是「一次调用的结果」、一半是「一条推送」，
 * 而两者的读法根本不同。
 *
 * 字段名一律照后端的 `to_dict()` 抄。抄错一个字母 TS 不会报错（事件载荷是
 * 运行时才分叉的），所以改后端时**必须**回来对一遍。
 */

/** 课堂状态机（P3 §2.1）。`paused` 也算「正在上」，`ended` 是唯一终态。 */
export type ClassroomStatus =
  | 'idle'
  | 'lecture'
  | 'discussing'
  | 'quiz_wait'
  | 'board_show'
  | 'paused'
  | 'ended'

/** `auto` = 时间线自己走；`manual` = 逐页手翻（推送关掉时 `auto` 会降级成它）。 */
export type ClassroomMode = 'auto' | 'manual'

/** 消息的三类说话人：老师、AI 同学、真人（我），外加系统提示。 */
export type SpeakerKind = 'teacher' | 'student_ai' | 'me' | 'system'

/** §5 的七种消息类型。`lecture` 是讲稿，其余是互动与系统提示。 */
export type MessageType =
  | 'lecture'
  | 'question'
  | 'supplement'
  | 'reflect'
  | 'answer'
  | 'comment'
  | 'system'

export type HandStatus = 'waiting' | 'called' | 'done' | 'canceled'

/** 板书画笔的起笔人：AI 老师，或者我（`board_sync` 上报的那些）。 */
export type StrokeAuthor = 'teacher' | 'me'

// --- HTTP（§4.1）---

/** 会话状态：`GET /sessions/{id}` 与 `POST /sessions` 的公共部分。 */
export interface ClassroomSession {
  id: string
  courseId: string
  ownerId: string
  mode: ClassroomMode
  status: ClassroomStatus
  pageNo: number
  beatIdx: number
  elapsedMs: number
  totalMs: number
  speed: number
  startedAt: string
  endedAt: string
  createdAt: string
}

export interface ClassroomPresenceMember {
  userId: string
  name: string
  role: string
}

/** 名单里的 AI 同学。没有 `userId`：它不是连接进来的人，是这堂课的一个角色。 */
export interface ClassroomAiMember {
  /** 角色的 `code`，与消息里的 `speaker` 同源 —— 头像与音色都按它认人。 */
  code: string
  name: string
  /** 角色头像色（`AgentRole.avatarColor`），空串表示没配。 */
  color: string
  role: string
}

/** 「在线 N」数的就是 `members` 的长度 —— 同一个人开两个标签页也只算一个。 */
export interface ClassroomPresence {
  online: number
  members: ClassroomPresenceMember[]
  /**
   * 这堂课里的 AI 同学（人数由设置页「AI 同学数量」决定）。
   *
   * **不计入 `online`**：那个数是「几个人真的连进来了」，用来判断学生到齐没有；
   * AI 同学不连进来，它们一直都在。两个数分开，两个问题才都答得上来。
   */
  aiMembers: ClassroomAiMember[]
}

/** `GET /sessions/{id}`：会话行 + 课名 + 在线情况。 */
export interface ClassroomSummary extends ClassroomSession {
  courseTitle: string
  presence: ClassroomPresence
}

/** 时间线上的一句讲稿。`durationMs` 是音频真时长，没有音频时由字数估。 */
export interface TimelineBeat {
  beatId: string
  text: string
  durationMs: number
  startMs: number
}

export interface TimelinePage {
  pageNo: number
  chapterNo: number
  kind: string
  title: string
  beats: TimelineBeat[]
  /** 题面（**不含答案与解析**，那两个只在判定之后给） */
  quiz: ClassroomQuiz | null
  boardPlan: { tool: string; desc: string; atBeat: string }[]
  discussion: string[]
  startMs: number
  durationMs: number
}

export interface ClassroomTimeline {
  pages: TimelinePage[]
  totalMs: number
  pageCount: number
}

/** `POST /sessions`：开课 + 一张只活 60 秒的接入票据 + 整条时间线。 */
export interface ClassroomStart {
  sessionId: string
  wsToken: string
  mode: ClassroomMode
  status: ClassroomStatus
  timeline: ClassroomTimeline
}

/** `POST /sessions/{id}/ticket`：重签票据（刷新恢复 / 断线重连）。 */
export interface ClassroomTicket {
  wsToken: string
  ttlSec: number
}

/** 一条消息（讨论区的一条 / 字幕的一条，同一张表的同一行）。 */
export interface ClassroomMessage {
  id: string
  sessionId: string
  speaker: string
  speakerKind: SpeakerKind
  type: MessageType
  text: string
  pageNo: number | null
  /** 非空表示这条是照着某个 beat 讲的 —— 它同时是一条字幕 */
  beatId: string
  audioUrl: string
  quoteMsgId: string
  ts: string
}

export interface MessagePage {
  items: ClassroomMessage[]
  hasMore: boolean
  total: number
}

export interface HandItem {
  id: string
  userId: string
  name: string
  ts: string
  calledAt: string
  status: HandStatus
}

/** `POST /raise-hand` 与 WS 的 `hand_queue` 共用这一份。 */
export interface HandQueueState {
  queue: HandItem[]
  called: HandItem | null
}

export interface StrokePoint {
  x: number
  y: number
}

/** 一笔板书。坐标是 0~1 的归一化值，前端乘画布尺寸。 */
export interface BoardStroke {
  id: string
  sessionId: string
  pageNo: number
  strokeNo: number
  tool: string
  color: string
  width: number
  points: StrokePoint[]
  text: string
  atBeatId: string
  durMs: number
  author: StrokeAuthor
}

/**
 * 题面。**`options` 是四句话、`answer` 也是其中一句话** —— 不是 A/B/C/D 键。
 * 提交时把选中的那句话原样发回去（`POST /quiz-submit` 的 `option`）。
 *
 * 下发时 `answer` / `explain` 缺席（后端 `quiz_question` 会删掉它们）；
 * 判定之后由 `quiz_result` 把两者一起给回来。
 */
export interface ClassroomQuiz {
  pageNo: number
  stem: string
  options: string[]
  answer?: string
  explain?: string
  conceptTag?: string
}

/** `quiz_result` 的载荷。`branch` 有三种：pass（答对）/ remedial（AI同学补充）/ review（插入复习页）。 */
export interface QuizResult {
  pageNo: number
  correct: boolean
  option: string
  answer: string
  explain: string
  branch: 'pass' | 'remedial' | 'review'
  /** P6.1：分支反馈事件的载荷（quiz_feedback 事件）。 */
  feedback?: {
    branch: string
    message?: { speaker: string; text: string }
    reviewPage?: Record<string, unknown>
    [key: string]: unknown
  }
}

// --- 课堂记录（`GET /record`）---

export interface RecordSubtitle {
  beatId: string
  pageNo: number
  speaker: string
  text: string
  audioUrl: string
  ts: string
}

export interface RecordStats {
  messages: number
  subtitles: number
  boardPages: number
  strokes: number
  quizAttempts: number
  quizCorrect: number
  durationMs: number
  /** 思辨那一组（`scaffold.stats_of`）：只报次数、不打分。 */
  thinkingTrails: number
  studentTurns: number
  openTrails: number
}

/** 轨迹上的一环演的是哪一出。`question` 是学生问的那句，`ask` 是老师的追问。 */
export type RecordTrailRole = 'question' | 'ask' | 'reply' | 'answer'

export interface RecordTrailStep {
  id: string
  speaker: string
  speakerKind: SpeakerKind
  type: MessageType
  role: RecordTrailRole
  text: string
  ts: string
  pageNo: number
}

/**
 * 一条思辨轨迹（N4）：**一次引导**从头到尾的那几句话。
 *
 * 链子是 `messages.quote_msg_id` 折出来的（后端 `scaffold.build_trails`），
 * 所以它和「消息记录」那一栏是同一批数据 —— 区别只在分组：这里一次引导一条。
 *
 * `status` 只有两种：`closed`（老师收束了）、`open`（没接住 / 还没收束）。
 * 后者是这个功能真正想看的东西 —— 它指出**哪一页没讲清**。
 */
export interface RecordTrail {
  rootId: string
  pageNo: number
  question: string
  ts: string
  status: 'closed' | 'open'
  /** 这一条链上学生自己说了几句（含提问本身）。 */
  studentTurns: number
  steps: RecordTrailStep[]
}

export interface ClassroomRecord {
  session: ClassroomSession
  courseTitle: string
  participants: (ClassroomPresenceMember & { joinedAt: string; leftAt: string })[]
  subtitles: RecordSubtitle[]
  messages: ClassroomMessage[]
  boards: { pageNo: number; strokes: BoardStroke[] }[]
  trails: RecordTrail[]
  quizzes: {
    pageNo: number
    option: string
    correct: boolean
    nodeId: string
    responseMs: number
    ts: string
  }[]
  stats: RecordStats
}

// --- WebSocket（§4.2）---

/** 下行的十一种事件，外加两条**每连接私有**的帧（`error` / `ping`）。 */
export type ClassroomEvent =
  | ({ type: 'state' } & ClassroomStatePayload)
  | ({ type: 'speak' } & SpeakPayload)
  | { type: 'speak_end'; turnId: string; preempted?: boolean }
  | { type: 'subtitle'; beatId: string; text: string; pageNo: number }
  | { type: 'typing'; speaker: { code: string; name: string }; pageNo: number }
  | { type: 'message'; msg: ClassroomMessage }
  | ({ type: 'hand_queue' } & HandQueueState)
  | { type: 'board'; pageNo: number; strokes: BoardStroke[] }
  // 题面是**平铺**的（后端 `quiz_question` 返回的就是那一个 dict），
  // 没有外面再套一层 `quiz` 键
  | ({ type: 'quiz' } & ClassroomQuiz)
  | ({ type: 'quiz_result' } & QuizResult)
  | { type: 'quiz_feedback'; pageNo: number; branch: string; message?: unknown; reviewPage?: unknown }
  | ({ type: 'presence' } & ClassroomPresence)
  | { type: 'error'; code: string; message: string; recoverable?: boolean }
  | { type: 'ping'; ts?: string }

/** 三种事件的公共信封：除 `error` / `ping` 外都带这三个字段。 */
export interface EventMeta {
  seq: number
  eventId: string
  ts: string
}

export interface ClassroomStatePayload {
  status: ClassroomStatus
  pageNo: number
  beatIdx: number
  elapsedMs: number
  totalMs: number
  speed: number
}

/** `speak` 的载荷（后端 `Turn.to_dict()`）。**音频可能是空的** —— 见下面那条。 */
export interface SpeakPayload {
  turnId: string
  speaker: { code: string; name: string }
  speakerKind: SpeakerKind
  text: string
  /**
   * 讲稿这一句的音频。**空串是常态，不是异常**：
   * 讲稿的音频要预合成过才有；教师答疑的是当场合成的，配不上 TTS 就没有声音。
   * 播放器据此退到「只显示文字、按 `speak_end` 收尾」。
   */
  audioUrl: string
  /** 这条发言覆盖的讲稿 beat（只有讲稿类发言非空） */
  beats: string[]
  kind: string
  priority: number
  pageNo: number
}

// --- P6.1 学情总览 ---

/** 每章掌握度（`GET /mastery` 返回的 `chapters` 里的一项）。 */
export interface ChapterMastery {
  chapterNo: number
  total: number
  correct: number
  /** 0~1 之间的小数，前端乘 100 显示百分比 */
  mastery: number
}

/** 错题列表里的一条。 */
export interface WrongQuestion {
  pageNo: number
  nodeId: string
  option: string
  correct: boolean
  responseMs: number
  ts: string
  chapterNo: number
  conceptTag: string
}

/** 动态插入的复习页。 */
export interface ReviewPageItem {
  id: string
  sessionId: string
  courseId: string
  sourcePageNo: number
  insertedAfterPageNo: number
  dslJson: string
  triggerReason: string
  conceptTag: string
  createdAt: string
}

/** `GET /sessions/{id}/mastery` 的完整响应。 */
export interface MasteryData {
  chapters: ChapterMastery[]
  wrongQuestions: WrongQuestion[]
  reviewPages: ReviewPageItem[]
}
