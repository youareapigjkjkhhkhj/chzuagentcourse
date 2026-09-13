/**
 * 各模块接口（P0 §4）。一个函数对一个端点，名字与后端路由一一对应。
 */

import { API_BASE, del, get, post, put } from '@/api/client'
import type {
  AsrResult,
  AudioManifest,
  BudgetPatch,
  BudgetPayload,
  Capabilities,
  ChatMessageList,
  ChatRollbackResult,
  ChatSendResult,
  CourseCard,
  CourseDetail,
  CourseList,
  CoursePageItem,
  CourseQuery,
  CourseUsage,
  ExportCreatePayload,
  ExportItem,
  ExportList,
  GenerationSettings,
  GenerationStart,
  GenJobView,
  HealthInfo,
  JobTimeline,
  MaterialChunk,
  MaterialChunkList,
  MaterialDetail,
  MaterialItem,
  MaterialList,
  MaterialSearchResult,
  NarrateResult,
  OutlineSubmit,
  OutlineTree,
  PageVersion,
  PreviewResult,
  ProviderCard,
  ProviderList,
  ProbeResult,
  RewriteResult,
  RoleList,
  SaveProviderPayload,
  SkillCatalogue,
  StartGenerationPayload,
  TtsResult,
  UsageGroupBy,
  UsageModels,
  UsageReport,
  UsageSummary,
  VoiceList,
  VoiceSettings,
  VoiceTicket,
} from '@/types/api'

// --- 健康与能力（§4.1）---

export const fetchHealth = () => get<HealthInfo>('/health')

export const fetchCapabilities = () => get<Capabilities>('/capabilities')

// --- 服务商设置（§4.2）---

export const fetchProviders = () => get<ProviderList>('/settings/providers')

export const saveProvider = (id: string, payload: SaveProviderPayload) =>
  put<ProviderCard>(`/settings/providers/${id}`, payload)

/** 测试连接。返回的是探活结果本身，失败原因在 `error` 里（不是抛异常）。 */
export const probeProvider = (id: string) =>
  post<ProbeResult>(`/settings/providers/${id}/test`)

export const enableProvider = (id: string) =>
  post<ProviderCard>(`/settings/providers/${id}/enable`)

// --- 语音与生成参数（§4.2）---

export const fetchVoice = () => get<VoiceSettings>('/settings/voice')

export const saveVoice = (patch: Partial<VoiceSettings>) =>
  put<VoiceSettings>('/settings/voice', patch)

export const fetchGeneration = () => get<GenerationSettings>('/settings/generation')

export const saveGeneration = (patch: Partial<GenerationSettings>) =>
  put<GenerationSettings>('/settings/generation', patch)

// --- 内置角色（§4.2）---

export const fetchRoles = () => get<RoleList>('/agents/roles')

// --- 课程库（P1 §4）---

/** 课程列表。`status` / 分页都交给服务端，前端不自己筛一遍。 */
export const fetchCourses = (query: CourseQuery = {}) =>
  get<CourseList>('/courses', { params: pruned(query) })

export const fetchCourse = (id: string, options: { withPages?: boolean } = {}) =>
  get<CourseDetail>(`/courses/${id}`, {
    params: options.withPages ? { withPages: '1' } : {},
  })

/** 软删：后端置 `deleted_at`，页面与版本留在库里。 */
export const deleteCourse = (id: string) =>
  del<Pick<CourseCard, 'id'> & { deletedAt: string }>(`/courses/${id}`)

// --- 大纲与页面（P1-A3 / A7 / A11）---

export const fetchOutline = (id: string) => get<OutlineTree>(`/courses/${id}/outline`)

/**
 * 提交确认后的大纲。body 原样是那份章节树 —— 摘要里的「服务端自己会摘掉
 * 系统页再补一遍」说的是服务端的活，前端不替它算。
 */
export const confirmOutline = (id: string, outline: OutlineSubmit) =>
  post<OutlineTree & { resumed: boolean }>(`/courses/${id}/outline`, outline)

export const fetchPage = (id: string, pageNo: number) =>
  get<CoursePageItem>(`/courses/${id}/pages/${pageNo}`)

/** 只提交改动过的字段：空保存会白白推一个 rev 上去。 */
export const savePage = (id: string, pageNo: number, patch: Record<string, unknown>) =>
  put<CoursePageItem>(`/courses/${id}/pages/${pageNo}`, patch)

/** AI 重写（同步）。用户点完就等着看结果，不套一层任务。 */
export const rewritePage = (id: string, pageNo: number, instruction: string) =>
  post<RewriteResult>(`/courses/${id}/pages/${pageNo}/rewrite`, { instruction })

export const fetchVersions = (id: string, pageNo: number) =>
  get<{ items: PageVersion[] }>(`/courses/${id}/pages/${pageNo}/versions`)

// --- 生成与任务（P1-B1 / B2）---

/** 开始生成。**立刻**返回，生成在后台跑（B1：接口本身 < 500ms）。 */
export const startGeneration = (payload: StartGenerationPayload) =>
  post<GenerationStart>('/courses/generate', payload)

/** SSE 地址。EventSource 不走 axios，所以这里拼完整路径。 */
export const streamUrl = (jobId: string) => `${API_BASE}/courses/generate/${jobId}/stream`

/** 轮询兜底：流断了、或者压根没接上流时靠它把「现在到哪了」问出来。 */
export const fetchJob = (jobId: string) => get<GenJobView>(`/jobs/${jobId}`)

export const cancelJob = (jobId: string) => post<GenJobView>(`/jobs/${jobId}/cancel`)

export const retryStep = (jobId: string, stepId: string) =>
  post<{ jobId: string; stepId: string; status: string }>(
    `/jobs/${jobId}/steps/${stepId}/retry`,
  )

/**
 * 断点续跑：从第一个没做完的步骤接着跑（P5-F5-9）。已写好的页面一页都不重写。
 *
 * 与「重试某一步」是两回事：重试是用户点着那一步说「再来一次」，
 * 续跑是「接着上次的地方往下跑」—— 服务端从状态里自己找断点，前端不必告诉它。
 */
export const resumeJob = (jobId: string) => post<GenJobView>(`/jobs/${jobId}/resume`)

/**
 * 任务时间线：每步耗时 / 重试次数 / token / 金额 / 失败归类（P5-F5-10）。
 *
 * 与 `fetchJob` 是一对：那个答「现在到哪了」（轮询用，要短），
 * 这个答「它是怎么走到这儿的」（任务卡展开时用，要全）。
 */
export const fetchJobTimeline = (jobId: string) =>
  get<JobTimeline>(`/jobs/${jobId}/timeline`)

// --- 材料（P4 §3.1）---

/** 上传一份材料。解析在后台跑（`status=parsing`），详情要轮询几次。 */
export const uploadMaterial = (file: File) => {
  const form = new FormData()
  form.append('file', file, file.name)
  return post<MaterialItem>('/materials', form)
}

export const fetchMaterials = (query: { status?: string; page?: number; size?: number } = {}) =>
  get<MaterialList>('/materials', { params: pruned(query) })

export const fetchMaterial = (fileId: string) => get<MaterialDetail>(`/materials/${fileId}`)

export const fetchMaterialChunks = (
  fileId: string,
  query: { page?: number; size?: number; section?: string } = {},
) => get<MaterialChunkList>(`/materials/${fileId}/chunks`, { params: pruned(query) })

/** 一个分块的原文（溯源徽标跳过来看的那一段）。 */
export const fetchMaterialChunk = (fileId: string, chunkId: string) =>
  get<MaterialChunk>(`/materials/${fileId}/chunks/${chunkId}`)

/** 边打边搜，所以空 `q` 直接不发请求（服务端也返回空列表，这里省一次往返）。 */
export const searchMaterials = (query: { q: string; fileIds?: string[]; topK?: number }) =>
  query.q.trim()
    ? get<MaterialSearchResult>('/materials/search', {
        params: pruned({ ...query, fileIds: query.fileIds?.join(',') }),
      })
    : Promise.resolve({ enabled: true, query: '', items: [] } as MaterialSearchResult)

/**
 * 删一份材料。被页面引用着时**第一次会被挡下来**（40901 + `impact`），
 * 把影响面给用户看清楚，他确认了再带 `force` 来一次（P4-A13）。
 */
export const deleteMaterial = (fileId: string, options: { force?: boolean } = {}) =>
  del<{ fileId: string; name: string }>(`/materials/${fileId}`, {
    params: options.force ? { force: '1' } : {},
  })

// --- 材料与课程（P4 §3.1 / F4-7 / F4-14）---

export const fetchCourseMaterials = (courseId: string) =>
  get<{ items: MaterialItem[] }>(`/courses/${courseId}/materials`)

export const attachMaterials = (courseId: string, fileIds: string[]) =>
  post<{ added: string[]; skipped: string[]; courseId: string }>(
    `/courses/${courseId}/materials`,
    { fileIds },
  )

/** 从课程里移除一份材料。材料本身留着 —— 它属于用户，不属于这门课。 */
export const detachMaterial = (courseId: string, fileId: string) =>
  del<{ courseId: string; fileId: string; affectedCitations: number }>(
    `/courses/${courseId}/materials/${fileId}`,
  )

// --- 工作台对话（P4 §3.2）---

export const fetchChatMessages = (courseId: string, after = 0) =>
  get<ChatMessageList>(`/courses/${courseId}/chat/messages`, { params: { after } })

export const sendChatMessage = (courseId: string, payload: { text: string; refPageNo?: number }) =>
  post<ChatSendResult>(`/courses/${courseId}/chat`, payload)

/** 回退：`messageId` = 丢掉它及其之后的消息；`seq` = 保留到第 seq 条。 */
export const rollbackChat = (courseId: string, payload: { messageId?: string; seq?: number }) =>
  post<ChatRollbackResult>(`/courses/${courseId}/chat/rollback`, payload)

export const fetchSkills = (courseId: string) => get<SkillCatalogue>(`/courses/${courseId}/skills`)

/** 工作台 SSE 地址（EventSource 不走 axios）。 */
export const chatStreamUrl = (courseId: string) =>
  `${API_BASE}/courses/${courseId}/chat/stream`

// --- 语音（P2 §4.1）---

/** 音色列表（带 `usable`）。设置页那份在 `/settings/voice`，这份是语音功能要的视图。 */
export const fetchVoices = () => get<VoiceList>('/voice/voices')

/** 试听：合成示例句并返回可播 URL。命中缓存时不重复计费（`cached: true`）。 */
export const previewVoice = (voiceId: string, payload: { text?: string; force?: boolean } = {}) =>
  post<PreviewResult>(`/voice/voices/${voiceId}/preview`, payload)

/** 单句合成（P2-A1）。`speed` / `tone` 进合成也进缓存键，响应里会回显。 */
export const synthesizeSpeech = (payload: {
  text: string
  voiceId?: string
  speed?: number
  tone?: string
  force?: boolean
}) => post<TtsResult>('/voice/tts', payload)

/** 整课预合成：入队后台任务，**立刻**返回当前清单（`readyCount / beatCount` 就是进度）。 */
export const narrateCourse = (id: string, options: { force?: boolean; pageNo?: number } = {}) =>
  post<NarrateResult>(`/courses/${id}/narrate`, pruned(options))

/** 音频清单 —— 播放器的唯一输入。 */
export const fetchAudioManifest = (id: string) =>
  get<AudioManifest>(`/courses/${id}/audio-manifest`)

/**
 * 识别一段音频（P2 兜底路径）。
 *
 * `filename` 必须带真后缀：后端按文件名判格式，而 `MediaRecorder` 默认出的
 * webm/opus 上游不认（会返回 40001 并说清原因）。那条路的替代品是
 * **实时语音**（`/ws/voice/realtime`），不是在这里硬塞一个 webm。
 */
export const transcribeAudio = (blob: Blob, filename = 'ask.wav') => {
  const form = new FormData()
  form.append('file', blob, filename)
  return post<AsrResult>('/voice/asr', form)
}

export const fetchVoiceUsage = (query: { refType?: string; refId?: string } = {}) =>
  get<UsageReport>('/voice/usage', { params: pruned(query) })

/**
 * 实时语音的会话票据（P2-F4）。**建连之前先取一张**，WS 那边没票不开门。
 *
 * 走这一趟 HTTP 是有意的：语音开关、上游配置、归属人三件事在这里判一次，
 * 答复是一封普通信封（40302 / 40201，都带 `fallback`）。直接连 WS 的话，
 * 这些原本说得清的原因会塌成浏览器的一句「连接失败」。
 */
export const fetchVoiceTicket = () => post<VoiceTicket>('/voice/ticket')

/**
 * 实时语音的 WS 地址。**EventSource/axios 都不走这条路**，只能自己拼 ——
 * 与 `streamUrl` 同一个理由：地址只有一个来源，散着写迟早对不上。
 *
 * 协议是 `/ws`（不是 `/api`），所以 Vite 里另有一条代理；生产是同源直连。
 *
 * 票据放在查询串里而不是子协议头里：浏览器没有别的办法在握手里带一个自定义
 * 值（`WebSocket` 构造函数只收 URL 与子协议），而子协议是**要回显**的 ——
 * 把一次性凭据放进回显的字段里，等于把它摊在后续每一条帧上。
 */
export function realtimeUrl(ticket: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const base = `${proto}//${window.location.host}/ws/voice/realtime`
  return ticket ? `${base}?ticket=${encodeURIComponent(ticket)}` : base
}

// --- 导出（P5 §4.1 / F5-6）---

/**
 * 建一次导出。**立刻返回**，渲染在后台跑 —— 轮询 `fetchExport` 看进度。
 *
 * 格式与范围对不上（比如课件导 `md`）当场 40001，不留到渲染时才发现。
 */
export const createExport = (courseId: string, payload: ExportCreatePayload) =>
  post<ExportItem>(`/courses/${courseId}/exports`, payload)

/** 这门课的导出历史（新的在前）。**列表里的 `fileUrl` 一律是空的**，见上面那条注释。 */
export const fetchCourseExports = (
  courseId: string,
  query: { page?: number; size?: number } = {},
) => get<ExportList>(`/courses/${courseId}/exports`, { params: pruned(query) })

/**
 * 单条导出的状态。**点下载之前用它取链接**：`fileUrl` 每次都会换一张新票，
 * 缓存上一次那张的结局是「下载失败，回去重新问一次」。
 */
export const fetchExport = (exportId: string) => get<ExportItem>(`/exports/${exportId}`)

/** 删一次导出（产物文件与那一行一起删）。正在跑的那一次会被挡住（40902）。 */
export const deleteExport = (exportId: string) =>
  del<{ exportId: string; removed: boolean }>(`/exports/${exportId}`)

// --- 用量与成本（P5 §4.2 / F5-7）---

/** 成本看板的数。`groupBy` 三选一（day / course / kind），日期缺省是最近 30 天。 */
export const fetchUsageSummary = (
  query: { from?: string; to?: string; groupBy?: UsageGroupBy } = {},
) => get<UsageSummary>('/usage/summary', { params: pruned(query) })

/** 单课明细：这门课的每一次 LLM / 语音调用。 */
export const fetchCourseUsage = (courseId: string, query: { limit?: number } = {}) =>
  get<CourseUsage>(`/usage/courses/${courseId}`, { params: pruned(query) })

/** 价目表与「现在真的在用哪几个模型」。 */
export const fetchUsageModels = () => get<UsageModels>('/usage/models')

// --- 预算（P5 §4.2 / F5-8）---

/** 预算与当前用量。每条都带着 `usedCost` / `alert`，界面不必自己拼两半数字。 */
export const fetchBudget = () => get<BudgetPayload>('/settings/budget')

/** 改预算。按作用域增量更新，**只认传了的字段**（`0 = 不限`）。 */
export const saveBudget = (patch: BudgetPatch | { budgets: BudgetPatch[] }) =>
  put<BudgetPayload>('/settings/budget', patch)

/**
 * 改价目表（P5 §4.2）。**读在 `/usage/models`，写在这里** —— 与预算同一套分法。
 *
 * `llm` 那段是**整段替换**（按模型名给全量），语音三条按 `priceField` 给单价：
 * `{llm: {'deepseek-chat': {promptPer1k: 1, completionPer1k: 3}}, tts: {perKChars: 0.2}}`。
 * 所以调用方要把表格里**所有**模型一起发回来，只发改过的那一个会把别的抹掉。
 */
export const savePricing = (payload: Record<string, unknown>) =>
  put<Record<string, unknown>>('/settings/pricing', payload)

/**
 * 去掉没填的查询参数：`?status=&page=` 这种空值后端会当成「传了个空串」校验。
 *
 * 形参写成 `object` 而不是 `Record<string, unknown>`：调用方交的多半是
 * `CourseQuery` 这类**具名接口**，接口没有索引签名，两者并不互相兼容。
 */
function pruned(query: object): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(query).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )
}
