/**
 * 与后端响应对齐的 TS 类型（P0 §3：types/ 放「与后端 Schema 对齐的 TS 类型」）。
 *
 * 这里的每个字段都对应 app/api 里的真实输出，改后端时同步改这里 ——
 * TS 编译不过，比上线后看见 undefined 便宜得多。
 */

/** 统一信封（P0-B1）。业务码与 HTTP 状态分离，所以 200 也可能是失败。 */
export interface Envelope<T> {
  code: number
  message: string
  data: T
  requestId: string
}

export type ProviderKind = 'llm' | 'tts' | 'asr' | 'realtime'

export interface Issue {
  level: 'warning' | 'error'
  code: string
  message: string
}

/** 一张服务商卡片。★ 永远不含明文或密文 Key。 */
export interface ProviderCard {
  id: string
  name: string
  kind: ProviderKind
  baseUrl: string
  defaultModel: string
  enabled: boolean
  /** 凭据齐备（库里填的，或 .env 里给的） */
  configured: boolean
  /** 现在真调得动：有适配器，且它已实现 */
  available: boolean
  /** 适配器的实现是否已完成；P0 的语音三件套为 false */
  implemented: boolean
  maskedKey: string
  missing: string[]
  latencyMs: number | null
  extra: Record<string, unknown>
  updatedAt: string
}

export interface ProviderList {
  items: ProviderCard[]
  total: number
}

export interface ProbeResult {
  ok: boolean
  latencyMs: number
  model: string
  provider: string
  error: string
  errorCode: string
}

export interface SaveProviderPayload {
  apiKey?: string
  baseUrl?: string
  defaultModel?: string
  clearApiKey?: boolean
}

export type Intonation = 'flat' | 'natural' | 'expressive'
export type Intensity = 'low' | 'medium' | 'high'
export type ScriptDetail = 'concise' | 'normal' | 'detailed'

export interface VoiceProfile {
  id: string
  name: string
  provider: string
  /** 厂商音色 ID。留空说明这把音色还没配到具体声音上 */
  voiceType: string
  gender: string
  style: string
  sampleUrl: string
  builtin: boolean
  speechRate: number
  /** 厂商音色 ID 是否已填 */
  configured: boolean
}

export interface VoiceSettings {
  voices: VoiceProfile[]
  teacherVoiceId: string
  speed: number
  intonation: Intonation
  asrEnabled: boolean
  asrBrowserLocal: boolean
}

export interface GenerationSettings {
  pageCount: number
  classmateCount: number
  intensity: Intensity
  scriptDetail: ScriptDetail
  autoIllustration: boolean
  quizPerChapter: boolean
  whiteboard: boolean
}

/** 滑杆的 min/max 与后端校验共用同一份常量（/api/capabilities）。 */
export interface GenerationLimits {
  minPageCount: number
  maxPageCount: number
  minClassmateCount: number
  maxClassmateCount: number
  minSpeed: number
  maxSpeed: number
  intonations: Intonation[]
  intensities: Intensity[]
  scriptDetails: ScriptDetail[]
}

export interface CapabilityInfo {
  available: boolean
  offline: boolean
  provider: string
  reason: string
  model?: string
}

export interface Capabilities {
  env: string
  version: string
  capabilities: Record<ProviderKind, CapabilityInfo>
  providers: Record<string, Record<string, Record<string, unknown>>>
  generation: GenerationLimits
}

export interface HealthInfo {
  status: string
  version: string
  db: string
  providers: Record<string, 'ready' | 'unconfigured'>
  llm: { provider: string; model: string }
  issues: Issue[]
}

export interface AgentRolePersona {
  tone: string
  style: string
  speechRate: number
  pitch: number
  systemHint: string
}

export interface AgentRole {
  id: string
  code: string
  name: string
  role: 'teacher' | 'student'
  avatarColor: string
  voiceProfileId: string
  builtin: boolean
  persona: AgentRolePersona
}

export interface RoleList {
  items: AgentRole[]
  total: number
}

// --- 课程与生成（P1 §3.3 / §4）---

export type CourseStatus = 'draft' | 'generating' | 'ready' | 'failed'
export type JobStatus = 'queued' | 'running' | 'paused' | 'done' | 'failed' | 'canceled'
export type StepStatus = 'wait' | 'running' | 'done' | 'failed' | 'skipped'
export type StepType = 'parse' | 'outline' | 'write' | 'quiz' | 'tts' | 'assemble'
export type PageStatus = 'pending' | 'ready' | 'failed'
export type PageKind =
  | 'cover'
  | 'outline'
  | 'concept'
  | 'figure'
  | 'example'
  | 'code'
  | 'quiz'
  | 'summary'
  | 'debate'

/** 首页卡片。页数/时长/状态都是 `courses` 行上的列，不在前端重算（A10）。 */
export interface CourseCard {
  id: string
  title: string
  topic: string
  status: CourseStatus
  pageCount: number
  readyPages: number
  durationMin: number
  roleCount: number
  cover: Record<string, unknown>
  progress: number
  jobId: string
  createdAt: string
  updatedAt: string
}

export interface CourseList {
  items: CourseCard[]
  total: number
  page: number
  size: number
}

/** 大纲树上的一个页节点。四态里的三个来自这里，`generating` 由 SSE 实时补。 */
export interface OutlinePageItem {
  pageNo: number
  kind: PageKind
  title: string
  status: PageStatus
  rev: number
}

export interface OutlineChapter {
  no: number
  title: string
  summary: string
  points: string[]
  discussion: string[]
  pages: OutlinePageItem[]
}

export interface OutlineTree {
  courseId: string
  title: string
  subtitle: string
  status: CourseStatus
  chapters: OutlineChapter[]
  /** 封面与大纲页（章号 0 的开篇） */
  front: OutlinePageItem[]
  /** 小结页（章号 0 的收尾） */
  back: OutlinePageItem[]
  pageCount: number
  jobId: string
  jobStatus: JobStatus | ''
  progress: number
  /** 「确认大纲」按钮亮不亮由服务端说了算（AGENTS §4.3） */
  confirmable: boolean
}

export interface CourseDetail extends CourseCard {
  subtitle: string
  chapters: OutlineChapter[]
  meta: Record<string, unknown>
  pages?: CoursePageItem[]
}

/** 一页的讲稿 beat。beatId / estSec 由服务端算，前端只提交 text。 */
export interface Beat {
  beatId?: string
  text: string
  estSec?: number
}

export interface SlideBullet {
  text: string
  emphasis?: string[]
}

export interface QuizItem {
  stem: string
  options: string[]
  answer: string
  explain: string
  conceptTag: string
}

/** 页面 DSL（§3.3）。P1 的九种页型共用这一个结构，各自用其中几项。 */
export interface SlideDsl {
  kind?: PageKind
  title?: string
  subtitle?: string
  bullets?: SlideBullet[]
  narration?: Beat[]
  visual?: { type: string; desc: string } | null
  interaction?: { askAtEnd: boolean; allowFreeChat: boolean } | null
  boardPlan?: { tool: string; desc: string; atBeat: string }[]
  sources?: string[]
  chapters?: { no: number; title: string; pages: number[] }[]
  steps?: string[]
  code?: { lang: string; content: string } | null
  explanation?: string[]
  quiz?: QuizItem | null
  hintScript?: string
  question?: string
  topic?: string
  sides?: { stance: string; points: string[] }[]
  arbiterSummary?: string
  meta?: Record<string, unknown> | null
  error?: string
}

export interface CoursePageItem {
  id: string
  courseId: string
  chapterNo: number
  pageNo: number
  kind: PageKind
  title: string
  status: PageStatus
  rev: number
  dsl: SlideDsl
}

export interface GenStep {
  id: string
  jobId: string
  seq: number
  type: StepType
  title: string
  status: StepStatus
  detail: Record<string, unknown>
  durationMs: number
  tokens: number
  error: string
  startedAt: string | null
  finishedAt: string | null
}

/** `GET /api/jobs/{jobId}` 的响应（轮询兜底）。 */
export interface GenJobView {
  id: string
  courseId: string
  status: JobStatus
  progress: number
  totalMs: number
  totalTokens: number
  options: Record<string, unknown>
  error: string
  createdAt: string
  updatedAt: string
  steps: GenStep[]
  currentStep: GenStep | null
  failedSteps: string[]
  retryable: boolean
}

/** `POST /api/courses/generate` 的响应（P1-B1：立刻返回，生成在后台）。 */
export interface GenerationStart {
  courseId: string
  jobId: string
  status: JobStatus
  stream: string
}

/** SSE `step.progress` 里那几批写页的子步骤（原型任务卡上的两行）。 */
export interface WriteBatch {
  label: string
  from: number
  to: number
  total: number
  done: number
  status: 'wait' | 'running' | 'done' | 'failed'
}

export interface PageVersion {
  id: string
  pageId: string
  rev: number
  reason: 'generate' | 'rewrite' | 'manual'
  instruction: string | null
  model: string | null
  tokens: number
  createdAt: string
}

/** 课程模式：讲授 / 研讨（P1-A12）。 */
export type CourseMode = 'lecture' | 'seminar'

export interface StartGenerationPayload {
  topic: string
  mode: CourseMode
  /**
   * 大纲写完就停下来等用户确认（F1-3 / P1-A3）。
   *
   * 后端默认 `false`（一路写完），首页那条路显式传 `true` —— 工作台大纲树上的
   * 增删改序只在确认点开着（`confirmable`），不传的话界面上永远走不到那一步。
   */
  confirmOutline?: boolean
}

export interface CourseQuery {
  status?: string
  page?: number
  size?: number
}

/** `POST /pages/{no}/rewrite` 的响应：新版本 + 这次重写花掉的 token。 */
export interface RewriteResult {
  page: CoursePageItem
  tokens: number
  model: string
}

/** 大纲提交的 body。页的真实字段（页号、状态）由服务端重排，这里只表达「要什么」。 */
export interface OutlineSubmitPage {
  pageNo?: number
  kind: PageKind
  title: string
  status?: PageStatus
  rev?: number
}

export interface OutlineSubmitChapter {
  no: number
  title: string
  summary?: string
  points?: string[]
  discussion?: string[]
  pages: OutlineSubmitPage[]
}

export interface OutlineSubmit {
  title: string
  chapters: OutlineSubmitChapter[]
}

/** 工作台上「一步正在跑」的视图：REST 的 GenStep 加上实时百分比。 */
export interface LiveStep extends GenStep {
  percent: number
}
