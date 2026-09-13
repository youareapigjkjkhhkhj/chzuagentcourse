/**
 * 课堂通道（P3-3 的连接契约 / P3-A10 刷新恢复 / P3-A11 断线重连）。
 *
 * 这一层管三件事，它们互相纠缠所以写在一起：**取票 → 建连 → 建连失败之后怎么办**。
 * 事件的语义归 `stores/classroom.ts`（它只认 `applyEvent`），这里只负责把事件
 * 从线上搬到它手里，外加两件只有这一层能做的活：
 *
 * 1. **答心跳**。服务端每 20s 发一条 `ping`，60s 收不到任何上行就判死（4408）。
 *    心跳走的是应用层的帧而不是协议层的 ping —— 协议层的 ping 由浏览器网络栈
 *    自动回，答不出「**页面**还在不在」（切后台的标签页照样有来有回）。
 *    所以这里必须主动回 `pong`，而且必须真的回：不回的话症状是「上了二十秒
 *    课就掉线」，看起来像网络问题，其实是没人应答。
 * 2. **重连**。断线之后每次都要**重新取一张票** —— 票据是一次性的，断开前
 *    那张已经用掉了。所以重连不是 `socket = new WebSocket(同一个地址)`，
 *    而是「再走一趟 `POST /sessions/{id}/ticket`，拿新票拼新地址」。
 * 3. **降级**。推送通道关着（`CLASSROOM_WS=false`）时课堂退到逐页手翻
 *    （P3-G3），页面据此显示提示条而不是一直转圈重试。
 *
 * **为什么降级只能靠 `POST /sessions` 回来的 `mode` 认**：那条路是真路由，
 * `sessions.require_ws()` 在 `Server.accept()` 之前就抛了 403 + 40302。
 * 但浏览器**读不到那封 403** —— WebSocket 的失败响应不暴露给脚本（安全考虑），
 * `onclose` 只会给一个 1006「异常关闭」。所以握手被拒这件事，从 socket 这一侧
 * 是认不出来的；能认出来的是开课时那句「你要 `auto`，服务端给了 `manual`」
 * （`sessions.start` 的 docstring 写着这个信号就是给前端用的）。页面把它读出来
 * 交给这里的 `disable()`，此后不再建连。
 */

import { onScopeDispose, ref, type Ref } from 'vue'

import { classroomSocketUrl, renewTicket } from '@/api/classroom'
import type { ClassroomEvent } from '@/types/classroom'

/** 连接状态。`reconnecting` = 断过、正在退避重试（顶栏那条灰条按它显示）。 */
export type SocketState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'

/**
 * WS 的那几个成员。`WebSocket` 结构上满足它，测试塞一个假的就行。
 *
 * 与 `useRealtimeVoice` 里的同名接口**故意各写一份**：那条通道收二进制帧
 * （音频），这条只收文本；那条要认的关闭码是自己的语义，这条要认的是 4403 /
 * 4408 / 4429。合成一个「什么都能收」的接口，等于让两个模块都依赖对方的
 * 假设 —— 而它们唯一的共同点只有 `send` 和 `close`。
 */
export interface SocketLike {
  /** 常量 1 = OPEN。测试的假 socket 可以不给，那就当它一直是开的。 */
  readyState?: number
  onopen: (() => void) | null
  onclose: ((event: { code?: number; reason?: string }) => void) | null
  onerror: (() => void) | null
  onmessage: ((event: { data: unknown }) => void) | null
  send(data: string): void
  close(code?: number): void
}

/** 关闭码（与后端 `channel.py` 的常量一一对应）。 */
export const CLOSE_NORMAL = 1000
export const CLOSE_FORBIDDEN = 4403
export const CLOSE_TIMEOUT = 4408
export const CLOSE_TOO_MANY = 4429

/**
 * 重连的退避（毫秒）。1s / 2s / 4s / 8s，之后每次都是 8s，一共试 5 次。
 *
 * 为什么要退避而不是「立刻重连」：断线多半是网络本身的问题，猛敲只会让
 * 恢复的那一刻一堆连接同时涌进来。为什么封顶 8s 而不是更久：课堂是**实时**的，
 * 等一分钟才回来，那节课已经讲过去了，重连也没意义。
 */
export const DEFAULT_BACKOFF_MS = [1000, 2000, 4000, 8000, 8000]

export interface ClassroomSocketOptions {
  /** 会话 id。写成取值函数：挂载时还没有会话（点了「开始上课」才有）。 */
  sessionId: () => string
  /**
   * 取一张票。默认走 `POST /sessions/{id}/ticket`（重连必用）。
   * 首次建连的票由 `POST /sessions` 一起给，用 `primeTicket()` 塞进来。
   */
  ticket?: (sessionId: string) => Promise<string>
  buildUrl?: (sessionId: string, ticket: string) => string
  createSocket?: (url: string) => SocketLike
  /** 补发起点：重连时把已经收到的最大 `seq` 报回去，服务端从它之后接着发。 */
  cursor: () => { pageNo: number; beatIdx: number; afterSeq: number }
  /** 收下一条事件。**去重之后**的（`seq` 不比已有的大的不会送到这里）。 */
  onEvent: (event: ClassroomEvent) => void
  /** 建连成功（发了 `hello`）。页面用它拉历史消息。 */
  onEnter?: () => void
  /** 重连成功 —— 与首次建连区分开，页面据此决定要不要重拉历史。 */
  onResume?: () => void
  backoffMs?: number[]
  timers?: Timers
}

export interface Timers {
  set: (handler: () => void, ms: number) => ReturnType<typeof setTimeout>
  clear: (handle: ReturnType<typeof setTimeout>) => void
}

export interface ClassroomSocket {
  state: Ref<SocketState>
  /** 走到「不重试了」时的那句话。空串表示还没到那一步。 */
  error: Ref<string>
  /** 降级提示（推送关掉时的那条路）。非空表示这条通道**不打算连**。 */
  fallback: Ref<string>
  /** 已经试了几次重连（顶栏「正在重连（第 2 次）」用它）。 */
  attempts: Ref<number>
  /** 把开课响应里那张票塞进来，供第一次建连使用。 */
  primeTicket: (ticket: string) => void
  /** 建连（幂等：已经连着就什么都不做）。 */
  open: () => Promise<void>
  /** 主动断开。此后不再重连。 */
  close: () => void
  /** 告诉这一层「推送通道关着」，那是哪条路。 */
  disable: (hint: string) => void
  /**
   * 上行一条。**没连上时静默丢掉**并返回 false —— 调用方据此知道这一下没发出去。
   *
   * 不排队补发：课堂的上行几乎全是「此刻的意图」（举手、翻页、答完这一句），
   * 断线期间攒下来、重连后一齐倒出去，倒出去的是一串**早就过期**的动作
   * （尤其是 `beat_done`，它会让时间线凭空跳好几格）。当前状态由 `state`
   * 事件在重连时重新对齐，不需要靠补发凑。
   */
  send: (message: Record<string, unknown>) => boolean
}

export function useClassroomSocket(options: ClassroomSocketOptions): ClassroomSocket {
  const buildUrl = options.buildUrl ?? classroomSocketUrl
  const createSocket = options.createSocket ?? ((target: string) => new WebSocket(target) as unknown as SocketLike)
  // 默认取票 = 重签一张（`POST /sessions/{id}/ticket`）。**不是** `renewTicket`
  // 本身：那一个的返回值是 `{wsToken, ttlSec}` 整封信，这一层只要票据那一段。
  const fetchTicket = options.ticket ?? (async (id: string) => (await renewTicket(id)).wsToken)
  const backoff = options.backoffMs ?? DEFAULT_BACKOFF_MS
  const timers: Timers = options.timers ?? {
    set: (handler, ms) => setTimeout(handler, ms),
    clear: (handle) => clearTimeout(handle),
  }

  const state = ref<SocketState>('idle')
  const error = ref('')
  const fallback = ref('')
  const attempts = ref(0)

  let socket: SocketLike | null = null
  let primed = ''
  /** 是「我们主动关的」还是「它自己断的」——决定要不要重连。 */
  let closing = false
  let timer: ReturnType<typeof setTimeout> | null = null
  /** 连过至少一次没有。第二次起就是重连，`hello` 里的说法不一样。 */
  let entered = false

  function send(message: Record<string, unknown>): boolean {
    const current = socket
    if (!current || !isOpen(current)) return false
    try {
      current.send(JSON.stringify(message))
      return true
    } catch {
      // 通道刚断：onclose 会接手，这里不重复报错
      return false
    }
  }

  /**
   * 上行只在 socket 真的开着的时候发。`readyState` 是标准字段（1 = OPEN）；
   * 测试的假 socket 不给它，那就当它一直开着 —— 假 socket 的存在本身就是
   * 「这条连接是好的」这个前提。
   */
  function isOpen(target: SocketLike): boolean {
    return target.readyState === undefined || target.readyState === 1
  }

  async function open(): Promise<void> {
    if (fallback.value) return
    if (socket) return
    closing = false
    error.value = ''
    state.value = entered ? 'reconnecting' : 'connecting'

    const sessionId = options.sessionId()
    if (!sessionId) {
      state.value = 'closed'
      return
    }

    // 取票。**每一次建连都要一张新的**：首次那张由 `primeTicket` 给（开课响应
    // 里带的），重连的每一张都得重新签 —— 票据一次性，断开前那张已经用掉了。
    let ticket = primed
    primed = ''
    if (!ticket) {
      try {
        ticket = await fetchTicket(sessionId)
      } catch (err) {
        // 取不到票就别建连了。**这里不重试**：取票失败是 HTTP 上的答复
        // （课已经结束了 40901、不是我的课 404、后端没起来 -1），
        // 再试几次得到的还是同一句，不如直接把它说出来。
        giveUp(messageOf(err, '拿不到进课堂的票据，请刷新页面重试'))
        return
      }
    }

    await new Promise<void>((resolve) => {
      let admitted = false
      const channel = createSocket(buildUrl(sessionId, ticket))
      socket = channel

      channel.onopen = () => {
        admitted = true
        state.value = 'open'
        attempts.value = 0
        const at = options.cursor()
        send({
          type: 'hello',
          // 票在 URL 里（`?ticket=`），路由已经核销过了 —— 这里再塞一遍
          // 等于把一张一次性凭据摊在每一条帧都可能被记下来的地方，
          // 而它并不会被读第二次（`channel._enter` 认过人就跳过 token）。
          token: '',
          resumeFrom: { sessionId, pageNo: at.pageNo, beatIdx: at.beatIdx, afterSeq: at.afterSeq },
          afterSeq: at.afterSeq,
        })
        if (entered) options.onResume?.()
        entered = true
        options.onEnter?.()
        resolve()
      }

      channel.onmessage = (event) => {
        if (typeof event.data !== 'string') return
        let payload: ClassroomEvent | { type: string }
        try {
          payload = JSON.parse(event.data)
        } catch {
          return // 不认识的帧直接忽略：它不是我们这个语义层的东西
        }
        if (payload.type === 'ping') {
          // 心跳：**一定要回**，不回 60s 后判死（4408）。见模块注释第 1 条。
          send({ type: 'pong', ts: (payload as { ts?: string }).ts ?? '' })
          return
        }
        options.onEvent(payload as ClassroomEvent)
      }

      channel.onerror = () => {
        // 浏览器不给细节（安全考虑）。真正的收尾在 onclose，这里只是
        // 把「这次 open 有结论了」放出来，免得调用方一直等着
        resolve()
      }

      channel.onclose = (event) => {
        socket = null
        resolve()
        const code = Number(event?.code ?? 0)
        if (closing) {
          state.value = 'closed'
          return
        }
        if (code === CLOSE_FORBIDDEN) {
          // 4403：这张票不是这堂课的，或者这堂课不给我看（P3-F1）。
          // **不重试**：再签一张票还是同一个人，结论一样。
          giveUp('这堂课不给你看，或者进课堂的票据已经失效了')
          return
        }
        if (!admitted && !entered && attempts.value === 0) {
          // 连第一次都没进去：多半是推送通道关着（握手被拒，浏览器只给 1006）。
          // 页面在开课那一步已经能从 `mode` 认出这件事，认出来就该调 `disable()`；
          // 没认出来的话这里退到同一条路，总好过转圈重试五次。
          giveUp('连不上课堂的推送通道，已切换为逐页手动翻页')
          return
        }
        scheduleRetry()
      }
    })
  }

  function scheduleRetry(): void {
    if (attempts.value >= backoff.length) {
      giveUp('与课堂的连接断了，重试了几次都没接上，请刷新页面')
      return
    }
    const wait = backoff[attempts.value]
    attempts.value += 1
    state.value = 'reconnecting'
    timer = timers.set(() => {
      timer = null
      void open()
    }, wait)
  }

  function giveUp(message: string): void {
    error.value = message
    state.value = 'closed'
    attempts.value = 0
    socket = null
  }

  function close(): void {
    closing = true
    if (timer !== null) {
      timers.clear(timer)
      timer = null
    }
    const current = socket
    socket = null
    state.value = 'closed'
    if (current) {
      try {
        current.close(CLOSE_NORMAL)
      } catch {
        // 已经断了：关不关都行，它不会再有回调
      }
    }
  }

  function disable(hint: string): void {
    fallback.value = hint
    close()
  }

  onScopeDispose(close)

  return {
    state,
    error,
    fallback,
    attempts,
    primeTicket: (ticket: string) => {
      primed = ticket
    },
    open,
    close,
    disable,
    send,
  }
}

/** 网络层失败没有 `message` 可读，退回调用方给的那句。 */
function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback
}
