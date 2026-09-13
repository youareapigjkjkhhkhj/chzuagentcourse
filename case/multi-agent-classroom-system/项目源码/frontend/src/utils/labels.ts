/**
 * 状态 → 中文 / CSS 类（P1-A4）。
 *
 * 状态词在首页卡片、大纲树、任务卡三处都要用，各写一份迟早会出现
 * 「卡片说生成中、树说待生成」这种自相矛盾的界面。
 */

import type { CourseStatus, PageKind, StepStatus, StepType } from '@/types/api'

/** 九种页型的中文名（P1 §3.2）。 */
export const PAGE_KIND_LABELS: Record<PageKind, string> = {
  cover: '封面',
  outline: '课程大纲',
  concept: '概念讲解',
  figure: '图解',
  example: '案例',
  code: '代码',
  quiz: '随堂测验',
  summary: '课程小结',
  debate: '研讨',
}

/**
 * 图示类型（`dsl.visual.type`）的中文名。
 *
 * 这个字段是模型自己写的自由文本 —— 提示词只要求「描述该配什么图」，没有
 * 圈定词表（`schema.py` 只兜了个空值 `diagram`）。所以这里**不是白名单**：
 * 认识的翻译成中文，不认识的原样显示（见 `visualTypeLabel`），
 * 页面上不会因为模型换了个词就空一块。
 *
 * 已知会出现的两类：真·图示词（diagram / figure / flow …），以及模型顺手
 * 把页型（cover / quiz / summary）当类型写的（跑真模型时两个演示课程里都有）。
 */
export const VISUAL_TYPE_LABELS: Record<string, string> = {
  diagram: '示意图',
  figure: '插图',
  flow: '流程图',
  chart: '图表',
  timeline: '时间轴',
  table: '表格',
  map: '地图',
  photo: '实拍图',
  // 页型漏进来时的兜底说法
  cover: '封面图',
  outline: '大纲图',
  concept: '概念图',
  example: '案例图',
  code: '代码图',
  quiz: '测验图',
  summary: '小结图',
  debate: '研讨图',
}

/** 图示类型 → 中文。词表里没有的原样返回，绝不显示成空白。 */
export function visualTypeLabel(type: string | null | undefined): string {
  const token = (type ?? '').trim()
  if (!token) return ''
  return VISUAL_TYPE_LABELS[token.toLowerCase()] ?? token
}

/** 课程状态（`courses.status`）。 */
export const COURSE_STATUS_LABELS: Record<CourseStatus, string> = {
  draft: '草稿',
  generating: '生成中',
  ready: '已生成',
  failed: '生成失败',
}

/** 课程状态对应的标签主题（TDesign 的 `theme`），与原型首页卡片一致。 */
export const COURSE_STATUS_THEMES: Record<
  CourseStatus,
  'default' | 'primary' | 'success' | 'danger' | 'warning'
> = {
  draft: 'default',
  generating: 'warning',
  ready: 'success',
  failed: 'danger',
}

/**
 * 大纲树上的四态（P1-A4）。前三个来自 REST 的页面状态，`generating` 由
 * SSE 的 `step.progress` 实时补 —— 所以这里比 `PageStatus` 多一个取值。
 */
export type PageState = 'pending' | 'ready' | 'failed' | 'generating' | 'editing'

export const PAGE_STATE_LABELS: Record<PageState, string> = {
  editing: '编辑中',
  ready: '完成',
  generating: '生成中',
  failed: '失败',
  pending: '待生成',
}

/** 四态的标签配色，取自原型 `workbench.html` 的 statusTag（编辑中=primary 等）。 */
export const PAGE_STATE_THEMES: Record<
  PageState,
  'default' | 'success' | 'primary' | 'danger' | 'warning'
> = {
  editing: 'primary',
  ready: 'success',
  generating: 'warning',
  failed: 'danger',
  pending: 'default',
}

/** 任务步骤状态 → `.task-step` 上的类名（原型里那四种样式）。 */
export const STEP_CLASSES: Record<StepStatus, string> = {
  wait: 'is-waiting',
  running: 'is-running',
  done: 'is-done',
  failed: 'is-failed',
  skipped: 'is-skipped',
}

/** 六步的短名。表格里放不下「解析需求与受众画像」，任务卡上放得下，这里只做兜底。 */
export const STEP_TYPE_LABELS: Record<StepType, string> = {
  parse: '解析',
  outline: '大纲',
  write: '写页',
  quiz: '测验',
  tts: '语音',
  assemble: '装配',
}

/**
 * 失败归类码 → 人话（P5-F5-10）。
 *
 * 这些码由服务端给（`llm.error_code_of` / 管线自己写的几个），前端**不判**、
 * 只翻译 —— 判断在两边各写一份，迟早会出现「后端记 timeout、前端说限流」。
 *
 * 与 `VISUAL_TYPE_LABELS` 同一条政策：**不是白名单**。认得的翻成中文，
 * 不认识的原样显示（见 `errorCodeLabel`）—— 码是后端加的，界面不该因为
 * 多了个新码就空一块。
 */
export const ERROR_CODE_LABELS: Record<string, string> = {
  // 上游给的（`error_code_of` 从适配器的 details 里取，或按错误码映射）
  timeout: '上游超时',
  rate_limit: '被限流',
  missing_api_key: '未配置密钥',
  schema_invalid: '返回格式不合规',
  upstream_error: '上游报错',
  // 管线自己写的
  interrupted: '被中断（服务重启过）',
  content_blocked: '内容被拦下',
  page_failed: '某一页生成失败',
  page_write_failed: '页面落库失败',
  no_pages: '一页都没写出来',
  no_chapters: '大纲里没有可写的章节',
  voice_all_failed: '语音全部合成失败',
  step_failed: '这一步失败',
}

/** 归类码 → 人话。没见过的码原样返回，绝不显示成空白。 */
export function errorCodeLabel(code: string | null | undefined): string {
  const token = (code ?? '').trim()
  if (!token) return ''
  return ERROR_CODE_LABELS[token] ?? token
}

/**
 * 四条链路的短名（P5-F5-7）。顺序与后端 `DAILY_KINDS` 的声明序一致 ——
 * 看板上的图例不该今天这个在前、明天那个在前。
 */
export const USAGE_KIND_LABELS = {
  llm: '大模型',
  tts: '语音合成',
  realtime: '实时语音',
  asr: '语音识别',
} as const

/** 作用域的中文名（预算表：日 / 单课 / 全部）。 */
export const BUDGET_SCOPE_LABELS = {
  day: '每日',
  course: '单课',
  global: '总额',
} as const

/**
 * 导出格式（P5-F5-1~F5-5）。括号里那句是**这个格式是干什么用的** ——
 * 光看「PPTX / HTML / PDF / MD」四个缩写，用户得挨个点一遍才知道选哪个。
 */
export const EXPORT_FORMAT_LABELS = {
  pptx: 'PPTX（可编辑课件）',
  html: 'HTML（离线课件，双击即看）',
  pdf: 'PDF（打印讲义）',
  md: 'Markdown（课堂记录）',
} as const

/** 一次导出的状态（`exports.status`）。 */
export const EXPORT_STATUS_LABELS = {
  queued: '排队中',
  running: '导出中',
  done: '可下载',
  failed: '导出失败',
} as const

export const EXPORT_STATUS_THEMES: Record<
  'queued' | 'running' | 'done' | 'failed',
  'default' | 'primary' | 'success' | 'danger' | 'warning'
> = {
  queued: 'default',
  running: 'warning',
  done: 'success',
  failed: 'danger',
}

/** 任务状态 → 会话头部那句话。 */
export const JOB_STATUS_LABELS = {
  queued: '排队中',
  running: '生成中',
  paused: '等确认大纲',
  done: '已完成',
  failed: '生成失败',
  canceled: '已取消',
} as const
