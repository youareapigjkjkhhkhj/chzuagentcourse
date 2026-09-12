/**
 * 各模块接口（P0 §4）。一个函数对一个端点，名字与后端路由一一对应。
 */

import { API_BASE, del, get, post, put } from '@/api/client'
import type {
  Capabilities,
  CourseCard,
  CourseDetail,
  CourseList,
  CoursePageItem,
  CourseQuery,
  GenerationSettings,
  GenerationStart,
  GenJobView,
  HealthInfo,
  OutlineSubmit,
  OutlineTree,
  PageVersion,
  ProviderCard,
  ProviderList,
  ProbeResult,
  RewriteResult,
  RoleList,
  SaveProviderPayload,
  StartGenerationPayload,
  VoiceSettings,
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
