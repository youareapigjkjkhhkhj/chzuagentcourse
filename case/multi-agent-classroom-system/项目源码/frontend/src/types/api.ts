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
  /** 苏格拉底式引导：学生提问先追问一层再给答案（关掉就是直接答）。 */
  socraticAnswer: boolean
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

/**
 * 材料功能的总开关（P4-G3）。`MATERIAL_ENABLED=false` 的部署里，
 * 工作台右侧那一栏整块不出现 —— 与语音的 `enabled`（`/api/voice/usage`）
 * 是同一种「这个能力没开」的答复，只是材料是一整套功能，挂在能力清单上。
 */
export interface MaterialCapability {
  enabled: boolean
  /** 单份材料的字节上限。上传前就能拦，不必先传一遍再吃 413。 */
  maxBytes: number
}

export interface Capabilities {
  env: string
  version: string
  capabilities: Record<ProviderKind, CapabilityInfo>
  providers: Record<string, Record<string, Record<string, unknown>>>
  generation: GenerationLimits
  materials: MaterialCapability
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

/**
 * 要点切成的小块。`math` 块的 `svg` 是服务端排好的行内公式，
 * 前端原尺寸贴进这一行就行（见 `SlideBullet.pieces`）。
 */
export interface SlidePiece {
  kind: 'text' | 'math'
  text: string
  svg?: string
}

export interface SlideBullet {
  text: string
  emphasis?: string[]
  /**
   * 有行内公式的要点才有这一项；没有就是条纯文字。
   * 前端**按 `pieces` 渲染、不按 `text` 渲染** —— `text` 里的 `$…$` 是
   * 原始标记，直接显示出来会带着美元号。`pieces` 拼起来等于 `text`。
   */
  pieces?: SlidePiece[]
}

export interface QuizItem {
  stem: string
  options: string[]
  answer: string
  explain: string
  conceptTag: string
}

/** 页面 DSL（§3.3）。P1 的九种页型共用这一个结构，各自用其中几项。 */
/**
 * 一页里的一条出处（F4-8）。`quote` 是材料原文里**一字不差的连续片段** ——
 * 后端核对过（子串匹配）才写进这里，所以前端可以直接把它显示成浮层。
 */
export interface SlideSource {
  materialId: string
  chunkId: string
  /** 材料里的页码（纯文本材料为 null）。徽标上写的就是它。 */
  pageNo: number | null
  sectionPath: string
  quote: string
  score: number
  /**
   * 材料名。页面溯源不带（抽屉那边按 `materialId` 现查），
   * 工作台摘要卡里的出处带 —— 那张卡上要写清「哪份材料的第几页」。
   */
  fileName?: string
}

/**
 * 可调参数（`visual.params`）。页面据此出一个滑块：拖到第 i 个取值，
 * 就把 `frames[i].svg` 换上去。
 */
export interface SlideVisualParam {
  name: string
  label: string
  values: number[]
}

/**
 * 这一页的图。
 *
 * 三种图（流程图 / 曲线图 / 公式）共用一个结构：`spec` 是模型给的结构、
 * `svg` 是服务端按它画好的那一张。**导出三格式取的就是 `svg` 这一帧** ——
 * 交互（滑块、逐拍揭示）只活在页面里。
 */
export interface SlideVisual {
  type: string
  desc: string
  svg?: string
  spec?: unknown
  /**
   * 可调参数的每一帧（服务端预渲染，与 `svg` 同一套画法）。
   * 只有「带 params 的曲线图」才有；没有参数时这两个字段都不出现。
   */
  frames?: { value: number; svg: string }[]
  params?: SlideVisualParam
}

export interface SlideDsl {
  kind?: PageKind
  title?: string
  subtitle?: string
  bullets?: SlideBullet[]
  narration?: Beat[]
  /**
   * 这一页的示意图。
   *
   * `svg` 是**服务端画好的**（生成时由 `generation.visual` 从 `spec` 确定性
   * 渲染，随 DSL 落库），前端只负责把它显示出来 —— 这里没有画图的逻辑，
   * 也就不存在「工作台预览和导出课件长得不一样」这件事。
   *
   * 老课程只有 `desc`（P1 原本只出描述），那时按文字提示画，不假装有图。
   */
  visual?: SlideVisual | null
  interaction?: { askAtEnd: boolean; allowFreeChat: boolean } | null
  boardPlan?: { tool: string; desc: string; atBeat: string }[]
  /** 这一页的出处（P4-8 的徽标读它）。**只有核对通过的才在里面**。 */
  sources?: SlideSource[]
  /** 有引文没核对上（P4-A7）：内容留着，但这一页要标出来「出处对不上」。 */
  sourceMissing?: boolean
  /** 材料没覆盖到的子主题（P4-A8），前端显示成黄色提示而不是让它编一段话。 */
  gaps?: string[]
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
  /**
   * 这一步一共跑过几次（P5-F5-10）。**累计**，重试与续跑都往上加、从不归零 ——
   * 「一次就成」与「重试三次才成」在界面上必须是两件事。
   */
  attempts: number
  /**
   * 失败原因归类：`timeout` / `rate_limit` / `missing_api_key` / `schema_invalid` /
   * `upstream_error` / `interrupted` …。空串表示这一步没失败过。
   *
   * 与 `error`（给人读的那句话）分工不同：这句话要能**分组**，
   * 「今天失败的五次是同一类原因」靠它才看得出来。
   */
  errorCode: string
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
  /**
   * 能不能「继续生成」（P5-F5-9）。判据在服务端（停下来了 **且** 还有没跑完的步骤）：
   * 前端自己拼 `status === 'failed'` 会漏掉「被取消」与「被重启打断」这两种，
   * 而它们恰恰是最该续的。
   */
  resumable: boolean
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

// --- 语音（P2 §4.1 / §6）---

/**
 * 降级到哪条路。**这个值只能由服务端给**（P2-B2）：前端自己猜「这个错是不是
 * 没配 Key、要不要改成打字」，就会有两份判断，而两份会在不同的时间点过期。
 */
export type VoiceFallback = 'text' | 'browser' | 'none'

/** 一个 beat 的音频状态。`missing` 是「这一句从来没合过」，不是「正在合成」。 */
export type BeatStatus = 'ready' | 'missing' | 'stale' | 'failed'

/** 字级时间戳。空数组表示上游没给 —— 这时按整句切换（P2-A3 的降级口径）。 */
export interface SubtitleCue {
  text: string
  startMs: number
  endMs: number
}

/** 清单里的一句（= 一页讲稿里的一段）。播放器的队列就是这个数组。 */
export interface AudioBeat {
  pageNo: number
  beatId: string
  /** 内容哈希。变了说明这句要重合成，播放 URL 也会跟着变 */
  textHash: string
  /** **空串就是没得播**：前端据此显示「未合成」，而不是一个点了没反应的播放键 */
  url: string
  durationMs: number
  text: string
  /** 没有音频时的节奏基准（秒） */
  estSec: number
  status: BeatStatus
  subtitles: SubtitleCue[]
}

/** `GET /api/courses/{id}/audio-manifest` —— 播放器的唯一输入。 */
export interface AudioManifest {
  courseId: string
  voiceId: string
  speed: number | null
  rate: number
  tone: string
  provider: string
  /** 上游是离线替身：有 URL 也是静音，界面得说出来 */
  simulated: boolean
  enabled: boolean
  /** 现在能不能真的出声（开关 + 音色 + 服务商三件事的合取） */
  available: boolean
  fallback: VoiceFallback | ''
  /** 为什么没有声音：voice_disabled / voice_not_configured / provider_not_configured */
  reason: string
  beatCount: number
  readyCount: number
  beats: AudioBeat[]
  /** 整课合成任务是不是正在跑（前端据此决定要不要轮询清单看进度） */
  running: boolean
}

/** `POST /api/courses/{id}/narrate`：清单 + 这次到底有没有真的排进去。 */
export interface NarrateResult extends AudioManifest {
  started: boolean
}

/** 试听 / 单句合成的响应（`durationMs` 与 `url` 是播放器要的两样）。 */
export interface PreviewResult {
  voiceId: string
  url: string
  /** 命中缓存 = 这次没花钱。界面据此说「这段是上次合成的」 */
  cached: boolean
  durationMs: number
  text: string
  provider: string
}

export interface TtsResult extends PreviewResult {
  speed: number | null
  tone: string
}

/** `GET /api/voice/voices` 的一个音色：设置页那套字段 + `usable`。 */
export interface VoiceItem extends VoiceProfile {
  /** 配置齐了**且**服务商可用。缺任何一半，试听点下去都是 40201/40001 */
  usable: boolean
}

export interface VoiceList {
  items: VoiceItem[]
  total: number
  /** 当前选中的音色 ID */
  current: string
  provider: string
  /** 语音总开关（`VOICE_ENABLED`）。关掉不是错误，是部署的决定（P2-G3） */
  enabled: boolean
  /** 有没有可用的合成服务商 */
  usable: boolean
}

export type UsageKind = 'tts' | 'realtime' | 'asr'

export interface UsageRow {
  kind: UsageKind
  units: number
  /** 计量单位由服务端定（chars / seconds），前端不换算 */
  unitName: string
  estCost: number
  calls: number
}

/** `GET /api/voice/usage`。金额是**估算**，没配单价时 `priced` 为 false。 */
export interface UsageReport {
  kinds: UsageRow[]
  totalCost: number
  /** 只要有一类没配单价，合计就是少报的 —— 界面得说出来，而不是显示 ¥0.00 */
  priced: boolean
  refType: string
  refId: string
  enabled: boolean
}

export interface AsrSegment {
  text: string
  startMs: number
  endMs: number
  final: boolean
}

export interface AsrResult {
  text: string
  final: boolean
  durationMs: number
  provider: string
  segments: AsrSegment[]
}

/** `POST /api/voice/ticket`：一次性、有时限，只用来开一条实时语音连接。 */
export interface VoiceTicket {
  ticket: string
  ttlSec: number
}

/** 实时语音的上行消息（P2 §4.2）。音频本身走**二进制帧**，不在这里。 */
export type RealtimeUplink =
  | {
      type: 'start'
      sessionId?: string
      roleCode?: string
      voiceType?: string
      mode?: 'voice_chat' | 'discussion'
      systemPrompt?: string
      context?: { courseId?: string; pageNo?: number }
    }
  | { type: 'audio'; seq?: number; final?: boolean }
  | { type: 'barge_in' }
  | { type: 'stop' }

/** 实时语音的下行消息。**前端不出现任何上游事件名**（P2 §4.2 的映射表）。 */
export type RealtimeDownlink =
  | { type: 'ready'; sessionId: string; dialogId: string; ttsFirstFrameMs: number }
  | { type: 'asr'; text: string; final: boolean }
  | { type: 'reply'; text: string; final: boolean }
  | { type: 'audio'; seq: number }
  | { type: 'barge_in_ack'; latencyMs: number }
  | { type: 'barge_in' }
  | { type: 'done'; usage: RealtimeUsage }
  | { type: 'usage'; usage: RealtimeUsage }
  | { type: 'closed'; reason: string }
  | { type: 'error'; code: string; message: string; fallback: VoiceFallback }

export interface RealtimeUsage {
  durationMs: number
  asrChars: number
  replyChars: number
  firstFrameMs: number
}

// --- 材料（P4 §3.1 / F4-1~F4-9）---

export type MaterialStatus = 'uploading' | 'parsing' | 'ready' | 'failed'

/** 一份材料。`fileId` 是它在所有接口里的名字（上传返回的也是它）。 */
export interface MaterialItem {
  fileId: string
  name: string
  ext: string
  sizeBytes: number
  /** 页数（纯文本材料是 0）。 */
  pages: number
  charCount: number
  chunkCount: number
  status: MaterialStatus
  /** 失败原因，是给用户看的那一句话。 */
  error: string
  createdAt: string
  /** 只有上传响应带：这份内容已经在库里了，没有再解析一遍（P4-C4）。 */
  duplicated?: boolean
}

export interface MaterialList {
  /** 材料总开关（P4-G3）。关着时 `items` 一定是空的，见 `MaterialCapability`。 */
  enabled: boolean
  items: MaterialItem[]
  page: number
  size: number
  hasMore: boolean
}

/** 目录树的一个节点（`sectionPath` 按 `>` 拆出来的）。`path` 是完整路径，点它去筛分块。 */
export interface MaterialTreeNode {
  title: string
  path: string
  chunkCount: number
  page: number | null
  children: MaterialTreeNode[]
}

/** 「删了会怎样」：有几页引用了它、关联在几门课里（P4-A13）。 */
export interface MaterialImpact {
  fileId: string
  name: string
  pages: number
  citations: number
  courses: string[]
}

export interface MaterialDetail extends MaterialItem {
  tree: MaterialTreeNode[]
  /** 材料过大，建议拆分（F4-13）。阈值在服务端，前端不记。 */
  oversized: boolean
  impact: MaterialImpact
}

export interface MaterialChunk {
  chunkId: string
  fileId: string
  chunkNo: number
  pageFrom: number | null
  pageTo: number | null
  sectionPath: string
  charCount: number
  text: string
}

export interface MaterialChunkList {
  total: number
  page: number
  size: number
  items: MaterialChunk[]
}

/** 一条检索结果：`text` 是完整的一块，前端拿它做高亮。 */
export interface MaterialHit {
  chunkId: string
  fileId: string
  fileName: string
  chunkNo: number
  page: number | null
  section: string
  score: number
  /** 命中了哪几个词、各几次（P4-A4：排序要说得清）。 */
  matched: string[]
  text?: string
}

export interface MaterialSearchResult {
  /** 同 `MaterialList.enabled`：关着时一定是空结果而不是报错（边打边搜那条路）。 */
  enabled: boolean
  query: string
  items: MaterialHit[]
}

// --- 工作台对话（P4 §3.2 / F4-10~F4-12）---

export type ChatRole = 'user' | 'assistant' | 'system'
export type SkillStatus = 'running' | 'ok' | 'failed'

/** 一条消息里调过的技能摘要（操作卡一次渲染用，细节在事件里）。 */
export interface ChatSkillCall {
  skill: string
  status: SkillStatus
  durationMs: number
  error: string
  result: Record<string, unknown>
}

export interface ChatMessageItem {
  id: string
  sessionId: string
  /** 会话内单调递增。回退的界就是它。 */
  seq: number
  role: ChatRole
  content: string
  skillCalls: ChatSkillCall[]
  refPageNo: number | null
  tokens: number
  createdAt: string
}

export interface ChatMessageList {
  sessionId: string
  items: ChatMessageItem[]
  lastSeq: number
  /** 这一轮还在后台跑（回退要先等它结束）。 */
  running: boolean
}

export interface ChatSendResult {
  sessionId: string
  /** 这条 assistant 消息的 id —— `agent.delta` 的每一帧都带着它。 */
  messageId: string
  userMessageId: string
  seq: number
  stream: string
}

export interface ChatRollbackResult {
  sessionId: string
  rolledBackTo: number
  removed: number
  removedMessages: { seq: number; role: ChatRole; content: string }[]
  lastKeptSeq: number
  pageNotice: string
}

export interface SkillParam {
  name: string
  desc: string
}

export interface SkillInfo {
  name: string
  title: string
  description: string
  params: SkillParam[]
}

export interface SkillCatalogue {
  items: SkillInfo[]
  maxActions: number
}

/**
 * 工作台 SSE 的帧载荷（P4 §3.3）。五种事件，字段按需出现 ——
 * 后端发的是 `events.emit` 那一刻的形状，一律当可选读。
 */
export interface ChatFramePayload {
  messageId?: string
  skillId?: string
  text?: string
  skill?: string
  args?: Record<string, unknown>
  why?: string
  status?: SkillStatus
  result?: Record<string, unknown> | null
  error?: string
  durationMs?: number
  tokens?: number
  /** `page.rewritten`：改的是哪一页。 */
  pageNo?: number
  rev?: number
  reason?: string
  removed?: boolean
  sources?: SlideSource[]
}

// --- 导出（P5 §4.1 / F5-6）---

/** 产物格式。`md` 只用于课堂记录，课件不走它。 */
export type ExportFormat = 'pptx' | 'html' | 'pdf' | 'md'

/** 导什么：整门课（课件）/ 一节课堂的记录（F5-5）。 */
export type ExportScope = 'course' | 'record'

export type ExportStatus = 'queued' | 'running' | 'done' | 'failed'

/** 渲染选项。原样留档在导出记录上 —— 改了水印开关重导就是另一份产物。 */
export interface ExportOptions {
  watermark?: boolean
  withNotes?: boolean
  withQuiz?: boolean
  /**
   * 用哪套 PPT 模板（配色+字体），值是后端 `exports/theme.py` 里的 key
   * （`default` / `swiss` / `tech`）。缺省 `default`。只对课件生效 ——
   * 课堂记录导的是逐字稿，不套模板。
   */
  template?: string
}

/** 一套可选的 PPT 模板。清单由后端下发（`ExportList.templates`），前端不写死。 */
export interface ExportTemplate {
  key: string
  name: string
}

/**
 * 一次导出（不是「一份产物」）：同一个课程可以导出很多次，各有各的进度、
 * 错误与过期时间。
 */
export interface ExportItem {
  exportId: string
  courseId: string
  /** 只有 `scope === 'record'` 时有值。 */
  sessionId: string
  format: ExportFormat
  scope: ExportScope
  status: ExportStatus
  /** 0~100，「画完几页 / 共几页」，不是估的。 */
  progress: number
  sizeBytes: number
  options: ExportOptions
  error: string
  /** 到期时间。到点文件与记录一起删，**不留「已过期」状态**。 */
  expiresAt: string
  finishedAt: string
  createdAt: string
  /** 「下载」按钮亮不亮由**服务端**说了算，前端不自己拼 `status === 'done'`。 */
  downloadable: boolean
  /**
   * 签过一次性票据的下载地址。**每次查询都会换一张新票**，所以：
   * 别缓存它、别复用 —— 点下载之前重新问一次状态再拿。
   *
   * 列表接口里这个字段**一律是空的**（二十行签二十张没人用的票），
   * 要下载就按 `exportId` 单独查一次。
   */
  fileUrl: string
}

export interface ExportList {
  items: ExportItem[]
  page: number
  size: number
  hasMore: boolean
  /**
   * 每种范围支持哪些格式（`{course: ['pptx', …], record: ['md', 'pdf']}`）。
   * 用它来铺格式选项，而不是在前端写死一份 —— 写死的那份和后端支持的一对不上，
   * 用户就会点到一个「这个格式不支持」的报错上。
   */
  supported: Record<ExportScope, ExportFormat[]>
  /**
   * 可选的 PPT 模板（配色+字体）。和 `supported` 一样由后端下发 ——
   * 模板是后端 `theme.py` 那份注册表说了算，前端写死一份迟早对不上。
   */
  templates: ExportTemplate[]
}

export interface ExportCreatePayload {
  format: ExportFormat
  scope?: ExportScope
  /** `scope=record` 时必填：导的是哪一节课堂。 */
  sessionId?: string
  options?: ExportOptions
}

// --- 任务时间线（P5 §4.1 / F5-10）---

/**
 * 一步（或整个任务）在账本上的样子（`model_calls`）。
 *
 * `failed` 的那几次**也在** `count` 里 —— 成功的次数是 `count - failed`。
 */
export interface StepCalls {
  count: number
  failed: number
  tokens: number
  /** 估算金额（LLM 那一档；语音按量计费，不在这张表里）。 */
  estCost: number
  latencyMs: number
  /** 失败过的错误码，按**发生顺序**去重（不排序：先超时后限流，是另一种故障）。 */
  errorCodes: string[]
  /** 这一步用过的模型（最多三个：多了说明中途换过服务商）。 */
  models: string[]
}

/** 时间线上的一步：REST 那份 `GenStep` 加上权重、百分比与账本。 */
export interface TimelineStep extends GenStep {
  /** 声明权重（六段进度条的宽度），与进度条同一份来源。 */
  weight: number
  percent: number
  calls: StepCalls
}

/**
 * 时间线的任务概要。`currentStep` 在这里是**步骤 id**（不是 `GenJobView` 里那个
 * 嵌套对象），`errorCode` 由失败的那一步推出来 —— 折叠着的任务卡也要能一眼
 * 看出「是限流还是没配 Key」。
 */
export interface TimelineJob extends Omit<GenJobView, 'steps' | 'currentStep'> {
  currentStep: string
  errorCode: string
}

export interface TimelineTotals {
  steps: number
  /** 各步耗时相加。与 `job.totalMs`（挂钟）是两个数，都留着：差得离谱说明有并发。 */
  stepMs: number
  /** 各步重试次数之和。「跑过三次才成」是用户该去看上游的那个信号。 */
  attempts: number
  retriedSteps: number
  failedSteps: number
  skippedSteps: number
  calls: StepCalls
  /**
   * 认不出归属的调用（有 `jobId` 却没落到任何一步上）。正常跑不会出现 ——
   * token 对不上账时，这是第一个该看的地方。
   */
  unattributed: StepCalls
}

export interface JobTimeline {
  job: TimelineJob
  steps: TimelineStep[]
  totals: TimelineTotals
  /** 金额口径的说明。**渲染出来**，不要吞掉：它是「这些数只是估算」的唯一出处。 */
  note: string
}

// --- 用量与成本（P5 §4.2 / F5-7）---

/** 四条链路。LLM 与语音三条的计量单位不同，所以看板上分开展示。 */
export type UsageLinkKind = 'llm' | 'tts' | 'realtime' | 'asr'

export type UsageGroupBy = 'day' | 'course' | 'kind'

/** 一条链路的量：token（LLM）或字符 / 秒（语音）。 */
export interface UsageBucket {
  kind: UsageLinkKind
  totalTokens: number
  totalUnits: number
  /** `totalUnits` 的单位名（chars / seconds），由服务端给。 */
  unitName: string
  estCost: number
  calls: number
}

export interface UsageTotals {
  totalTokens: number
  totalUnits: number
  estCost: number
  calls: number
}

/** 一个分组的合计：按天 / 按课。**没有 `kind` / `unitName`** —— 那一层在 `kinds` 里。 */
export interface UsageGroup extends UsageTotals {
  key: string
  label: string
  kinds: UsageBucket[]
}

/** 单课明细里的一次调用（LLM 与语音共用这一行形状）。 */
export interface UsageDetailRow {
  kind: UsageLinkKind
  at: string
  provider: string
  model: string
  tokens: number
  promptTokens: number
  completionTokens: number
  units: number
  unitName: string
  estCost: number
  latencyMs: number
  ok: boolean
  errorCode: string
  stepId: string
  refType: string
  refId: string
}

export interface CourseUsage {
  courseId: string
  items: UsageDetailRow[]
  /** 明细总条数（可能大于 `items.length`：接口有取回上限，不是分页）。 */
  total: number
  byKind: UsageBucket[]
  note: string
}

export interface UsageSummary {
  from: string
  to: string
  groupBy: UsageGroupBy
  currency: string
  /**
   * 分组结果。按天 / 按课是 `UsageGroup`；**按链路时是平铺的四条链路**
   * （与 `byKind` 同一份数据、同一个函数出的，后端 `_group` 的约定）——
   * 所以在「按链路」这一档直接读 `byKind`，那一层的壳长度恒为 1。
   */
  items: (UsageGroup | UsageBucket)[]
  /** 四条链路各花了多少。不管按什么分组，这一行都在。 */
  byKind: UsageBucket[]
  totals: UsageTotals
  /** 有链路没配单价时是 `false`：这时合计是**少报**的，界面要说出来。 */
  priced: boolean
  note: string
}

/** 价目表里的一行（LLM 按 token、语音按单位）。 */
export interface PricingRow {
  kind: UsageLinkKind
  /** 语音那三条没有模型名（空串）。 */
  model: string
  unitName: string
  /** LLM：每千 token 的价；语音没有这两个字段，看 `unitPrice`。 */
  promptPer1k?: number
  completionPer1k?: number
  /** 语音：每 `unitSize` 个单位的价。 */
  unitPrice?: number
  unitSize?: number
  priceField?: string
  priced: boolean
}

/** 正在使用的模型（已启用服务商的默认模型）。 */
export interface ActiveModel {
  provider: string
  model: string
  /** 是不是当前生效的那一个。 */
  active: boolean
}

export interface UsageModels {
  pricing: PricingRow[]
  models: ActiveModel[]
  unit: string
  note: string
}

// --- 预算（P5 §4.2 / F5-8）---

export type BudgetScope = 'day' | 'course' | 'global'

/**
 * 一条预算。`limitCost` / `limitTokens` 的 **0 = 不限**（不是「限额为零」）——
 * 所以判「超了没」看 `over`，不要自己拿用量去比 0。
 */
export interface BudgetRow {
  id: string
  scope: BudgetScope
  /** 单课预算的课程 id；`day` / `global` 是空串。 */
  refId: string
  limitTokens: number
  limitCost: number
  /** 用到这个比例就变黄（缺省 0.8）。**只告警，不拦任何事**。 */
  alertRatio: number
  enabled: boolean
  createdAt: string
  /** 这条预算当前的用量：单课的那几条各自带自己那门课的数。 */
  usedCost: number
  usedTokens: number
  /** 剩下的额度。**没配上限时是 0** —— 那表示不限，不是「一点不剩」。 */
  remainingCost: number
  remainingTokens: number
  /** 真的超了（会拦住下一次生成）。判据与服务端 `check()` 同源。 */
  over: boolean
  /** 接近上限（≥ `alertRatio`），界面变黄。 */
  alert: boolean
}

export interface BudgetPayload {
  /** `day` / `global` 各一条（没设过的补一条全 0 的），加上每门配过的课各一条。 */
  budgets: BudgetRow[]
  /** 三个作用域各一格；单课那一档说的是「还没指定哪门课」。 */
  current: Record<BudgetScope, BudgetRow>
  note: string
}

/** `PUT /api/settings/budget` 的一条改动。只认传了的字段，缺的保持原样。 */
export interface BudgetPatch {
  scope: BudgetScope
  /** `scope='course'` 时必填（不带就是「所有课程」，那是 `global` 的意思）。 */
  refId?: string
  limitTokens?: number
  limitCost?: number
  alertRatio?: number
  enabled?: boolean
}
