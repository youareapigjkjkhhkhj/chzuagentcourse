/**
 * 课堂接口（P3 §4.1）。一个函数对一个端点，名字与后端路由一一对应。
 *
 * **为什么另起一个文件而不是接着 `api/index.ts` 写**：那个文件是 P0 起的
 * 「所有模块都往里加」，已经两百多行；课堂这一组有九条 HTTP 加一条 WS 地址，
 * 加进去会让「课程」「语音」「课堂」三件事挤在一个 import 里。分开之后
 * 课堂页只需要 `import * as api from '@/api/classroom'`。
 * （`api/client.ts` 那层信封、超时、`X-Request-Id` 仍是共用的 —— 分开的只是
 * 「有哪些端点」，不是「怎么发请求」。）
 */

import { get, post } from '@/api/client'
import type {
  BoardStroke,
  ClassroomRecord,
  ClassroomStart,
  ClassroomSummary,
  ClassroomTicket,
  MessagePage,
  QuizResult,
} from '@/types/classroom'

/** 开始上课。返回票据（`wsToken`，只活 60 秒）+ 整条时间线，一步到位。 */
export const startSession = (payload: { courseId: string; mode?: string }) =>
  post<ClassroomStart>('/classroom/sessions', payload)

/** 会话状态。刷新之后前端问的第一条：现在讲到哪、谁还在线。 */
export const fetchSession = (id: string) => get<ClassroomSummary>(`/classroom/sessions/${id}`)

/**
 * 我正在上的课（还没结束的，新的在前）+ 每人上限。
 *
 * 开课时撞上上限（42901）的那句话是「先结束其中一堂再开新的」—— 这一条就是
 * 「其中一堂」在哪。没有它，那句话在界面上无处可点：卡住的人只能去翻记录页、
 * 或者干脆关掉浏览器等着会话自己过期。
 */
export const listSessions = () =>
  get<{ items: ClassroomSummary[]; limit: number }>('/classroom/sessions')

/**
 * 重签一张接入票据（P3-A10 刷新恢复 / P3-A11 断线重连）。
 *
 * **票据是一次性的**：建连时用掉就没了，所以「刷新页面」与「断线重连」都必然
 * 要再签一张。没有这一条，前端只剩「重新开一堂课」这一条路 —— 而那样同一门课
 * 会开成一串互不相干的会话，课上到一半的位置全留在旧的那一堂里。
 */
export const renewTicket = (id: string) =>
  post<ClassroomTicket>(`/classroom/sessions/${id}/ticket`)

/** 下课。重复调用是幂等的成功，不会改掉第一次的结束时刻。 */
export const endSession = (id: string, reason = '') =>
  post<{ session: ClassroomSummary; event: unknown }>(`/classroom/sessions/${id}/end`, { reason })

export const fetchRecord = (id: string) => get<ClassroomRecord>(`/classroom/sessions/${id}/record`)

/**
 * 消息分页。**历史消息走这一条，不走 WS**：新连接不会被重放整堂课的旧事件，
 * 连上之后先拉最近几十条，之后靠 `message` 事件增量拼接。
 */
export const fetchMessages = (id: string, query: { before?: string; size?: number } = {}) =>
  get<MessagePage>(`/classroom/sessions/${id}/messages`, {
    params: Object.fromEntries(
      Object.entries(query).filter(([, value]) => value !== undefined && value !== ''),
    ),
  })

/**
 * 举手 / 撤回 / 点名。三条动作与 WS 的 `hand` 是同一批服务端函数 ——
 * 同一个班里有人只能走 HTTP 时（推送关掉、socket 刚断），两条路必须给出
 * 同一个位次。
 *
 * 三条动作的回执形状**各不一样**（服务端就是这么给的）：`raise` 回
 * `{hand, position}`、`lower` 回 `{lowered}`、`call` 回被点名那一行或 null。
 * 真正的队列状态一律等 `hand_queue` 事件 —— 回执只是「这一次请求成了」，
 * 拿它去改本地队列就会有两个真相。
 */
export const sendHand = (
  id: string,
  action: 'raise' | 'lower' | 'call' = 'raise',
): Promise<{ hand?: unknown; position?: number; lowered?: number; called?: unknown }> =>
  post(`/classroom/sessions/${id}/raise-hand`, { action })

/**
 * 提交测验答案。
 *
 * `option` 是**整句选项文本**（题面里 `options` 的那一句话），不是 A/B 键 ——
 * 后端的判定就是拿它和 `answer` 比字符串。发成 "A" 会判错，而且看不出为什么。
 */
export const submitQuiz = (id: string, payload: { option: string; responseMs?: number }) =>
  post<QuizResult>(`/classroom/sessions/${id}/quiz-submit`, payload)

/** 这一页的板书笔画。没有板书的页返回空数组，不是 404。 */
export const fetchBoard = (id: string, pageNo: number) =>
  get<{ pageNo: number; strokes: BoardStroke[] }>(`/classroom/sessions/${id}/board/${pageNo}`)

/**
 * 课堂通道的 WS 地址。`EventSource`/axios 都不走这条路，只能自己拼 ——
 * 与 `streamUrl` / `realtimeUrl` 同一个理由：地址只有一个来源。
 *
 * 协议是 `/ws`（不是 `/api`），Vite 里另有一条代理；生产是同源直连。
 * 票据放在查询串里：浏览器没有别的办法在握手里带一个自定义值
 * （`WebSocket` 构造函数只收 URL 与子协议，而子协议是**要回显**的）。
 *
 * 空票据时**不拼 `?ticket=`**：那是「没带票」的意思，由服务端用 `hello.token`
 * 认人（认不出来给 4403）。拼一个空票等于拿一张不存在的票去开门，
 * 得到的会是一条含糊的 401，而不是「你没带票」。
 */
export function classroomSocketUrl(sessionId: string, ticket: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const base = `${proto}//${window.location.host}/ws/classroom/${encodeURIComponent(sessionId)}`
  return ticket ? `${base}?ticket=${encodeURIComponent(ticket)}` : base
}
