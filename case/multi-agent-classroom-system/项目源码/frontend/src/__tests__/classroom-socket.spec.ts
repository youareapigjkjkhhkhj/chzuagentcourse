/**
 * 课堂通道（P3-3 的连接契约）。
 *
 * 这一份盯的是**建连失败之后那几步**，因为它们是这一层唯一有判断的地方：
 * 取票 → 建连 → `hello` → 心跳 → 断了怎么办。事件本身的语义归 store
 * （`classroom-store.spec.ts`），这里只确认「事件有没有被原样送到 `onEvent`」。
 *
 * 真 WebSocket 在 jsdom 里连的是一台不存在的服务端，报什么错要看环境；
 * 所以 socket 与定时器都由用例注入 —— 想让它什么时候断就什么时候断。
 */

import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  CLOSE_FORBIDDEN,
  CLOSE_NORMAL,
  useClassroomSocket,
  type SocketLike,
  type Timers,
} from '@/composables/useClassroomSocket'
import type { ClassroomEvent } from '@/types/classroom'

/** 一个由用例掌控的假 socket：什么时候开、什么时候断、收到什么，全在这里。 */
class FakeSocket implements SocketLike {
  readyState = 0
  onopen: (() => void) | null = null
  onclose: ((event: { code?: number; reason?: string }) => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  sent: string[] = []
  closed: number | null = null

  constructor(readonly url: string) {}

  send(data: string): void {
    this.sent.push(data)
  }

  close(code?: number): void {
    this.closed = code ?? CLOSE_NORMAL
    this.readyState = 3
  }

  /** 服务端接受握手（浏览器在这一刻才把 readyState 置成 1）。 */
  accept(): void {
    this.readyState = 1
    this.onopen?.()
  }

  /** 服务端推一条。 */
  push(payload: unknown): void {
    this.onmessage?.({ data: typeof payload === 'string' ? payload : JSON.stringify(payload) })
  }

  /** 断开。`admitted` 为假时是「连第一次都没进去」。 */
  drop(code = 1006): void {
    this.readyState = 3
    this.onclose?.({ code })
  }

  /** 最后一条上行（解析过的）。 */
  last<T = Record<string, unknown>>(): T {
    return JSON.parse(this.sent[this.sent.length - 1] ?? '{}') as T
  }
}

/** 手工推进的定时器：退避等多久由用例说了算，不用真的等 8 秒。 */
function makeTimers() {
  const queue = new Map<number, { handler: () => void; ms: number }>()
  let id = 0
  const timers: Timers = {
    set: (handler, ms) => {
      id += 1
      queue.set(id, { handler, ms })
      return id as unknown as ReturnType<typeof setTimeout>
    },
    clear: (handle) => {
      queue.delete(handle as unknown as number)
    },
  }
  return {
    timers,
    /** 现在挂着几个待触发的定时器。 */
    get size() {
      return queue.size
    },
    /** 触发最早的那个（退避到点了）。 */
    fire(): void {
      const first = [...queue.entries()][0]
      if (!first) throw new Error('没有待触发的定时器')
      queue.delete(first[0])
      first[1].handler()
    },
    /** 这些定时器的间隔，按顺序。 */
    delays(): number[] {
      return [...queue.values()].map((item) => item.ms)
    },
  }
}

function setup(options: {
  cursor?: { pageNo: number; beatIdx: number; afterSeq: number }
  ticket?: (id: string) => Promise<string>
  backoff?: number[]
} = {}) {
  const sockets: FakeSocket[] = []
  const clock = makeTimers()
  const events: ClassroomEvent[] = []
  const entered = vi.fn()
  const resumed = vi.fn()
  const ticket =
    options.ticket ?? vi.fn(async (_id: string) => 'ticket-new')

  // 包在 `effectScope` 里：这个 composable 在组件里用，卸载时作用域停掉、
  // `onScopeDispose(close)` 收尾。测试里不给它作用域，那条清理路径就跑不到，
  // 而且 Vue 会为每一次调用喊一句「没有活跃的作用域」。
  const scope = effectScope()
  scopes.push(scope)
  const socket = scope.run(() =>
    useClassroomSocket({
      sessionId: () => 'cs1',
      ticket,
      buildUrl: (sessionId, value) => `ws://test/ws/classroom/${sessionId}?ticket=${value}`,
      createSocket: (url) => {
        const fake = new FakeSocket(url)
        sockets.push(fake)
        return fake
      },
      cursor: () => options.cursor ?? { pageNo: 3, beatIdx: 1, afterSeq: 7 },
      onEvent: (event) => events.push(event),
      onEnter: entered,
      onResume: resumed,
      backoffMs: options.backoff,
      timers: clock.timers,
    }),
  ) as ReturnType<typeof useClassroomSocket>

  return {
    socket,
    sockets,
    clock,
    events,
    entered,
    resumed,
    ticket,
    get last() {
      return sockets[sockets.length - 1]
    },
  }
}

/** 造出来的作用域都记一笔：用例结束后统一停掉，免得定时器漏到下一个用例里。 */
const scopes: ReturnType<typeof effectScope>[] = []

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  while (scopes.length) scopes.pop()?.stop()
})

describe('建连', () => {
  it('用票据拼地址，进课堂时把游标报上去（onopen 才发 hello）', async () => {
    const ctx = setup()
    ctx.socket.primeTicket('ticket-from-start')
    const opening = ctx.socket.open()
    await Promise.resolve() // 等取票那一步（有票就不用取，进到 createSocket）

    expect(ctx.sockets).toHaveLength(1)
    // 开课响应里那张票直接用掉：**不该再签一张**
    expect(ctx.ticket).not.toHaveBeenCalled()
    expect(ctx.last.url).toContain('ticket=ticket-from-start')
    expect(ctx.last.sent).toHaveLength(0) // 还没握手，什么都发不出去

    ctx.last.accept()
    await opening

    const hello = ctx.last.last<{
      type: string
      token: string
      afterSeq: number
      resumeFrom: { sessionId: string; pageNo: number; beatIdx: number; afterSeq: number }
    }>()
    expect(hello.type).toBe('hello')
    // 票在 URL 里（路由已经核销过），不在帧里再摊一遍
    expect(hello.token).toBe('')
    expect(hello.afterSeq).toBe(7)
    expect(hello.resumeFrom).toEqual({ sessionId: 'cs1', pageNo: 3, beatIdx: 1, afterSeq: 7 })
    expect(ctx.socket.state.value).toBe('open')
    expect(ctx.entered).toHaveBeenCalledTimes(1)
    expect(ctx.resumed).not.toHaveBeenCalled()
  })

  it('已经在连着的时候 open 是幂等的：不会多建一条', async () => {
    const ctx = setup()
    ctx.socket.primeTicket('t1')
    void ctx.socket.open()
    ctx.last.accept()
    await Promise.resolve()

    await ctx.socket.open()
    expect(ctx.sockets).toHaveLength(1)
  })

  it('没有票据时自己签一张（重连走的也是这条路）', async () => {
    const ctx = setup()
    void ctx.socket.open()
    await Promise.resolve()
    await Promise.resolve()

    expect(ctx.ticket).toHaveBeenCalledWith('cs1')
    expect(ctx.last.url).toContain('ticket=ticket-new')
  })

  it('没有会话号时不建连：课还没开出来', async () => {
    const sockets: FakeSocket[] = []
    const socket = useClassroomSocket({
      sessionId: () => '',
      createSocket: (url) => {
        const fake = new FakeSocket(url)
        sockets.push(fake)
        return fake
      },
      cursor: () => ({ pageNo: 0, beatIdx: 0, afterSeq: 0 }),
      onEvent: () => {},
    })

    await socket.open()
    expect(sockets).toHaveLength(0)
    expect(socket.state.value).toBe('closed')
  })

  it('取票失败不重试，直接把那句话说出来', async () => {
    const ctx = setup({ ticket: vi.fn(async () => Promise.reject(new Error('课堂已结束'))) })
    await ctx.socket.open()

    expect(ctx.socket.state.value).toBe('closed')
    expect(ctx.socket.error.value).toBe('课堂已结束')
    expect(ctx.clock.size).toBe(0) // 再试几次得到的还是同一句
  })
})

describe('心跳与消息', () => {
  it('ping 回 pong，并且**不交给 onEvent** —— 它不是课堂内容', async () => {
    const ctx = setup()
    ctx.socket.primeTicket('t1')
    void ctx.socket.open()
    ctx.last.accept()
    await Promise.resolve()
    ctx.last.sent = []

    ctx.last.push({ type: 'ping', ts: '2026-09-13T10:00:00' })

    expect(ctx.last.last()).toEqual({ type: 'pong', ts: '2026-09-13T10:00:00' })
    expect(ctx.events).toHaveLength(0)
  })

  it('把服务端的事件原样交给 store', async () => {
    const ctx = setup()
    ctx.socket.primeTicket('t1')
    void ctx.socket.open()
    ctx.last.accept()
    await Promise.resolve()

    ctx.last.push({ type: 'subtitle', beatId: 'b1', text: '第一句', pageNo: 1, seq: 1 })
    expect(ctx.events).toHaveLength(1)
    expect(ctx.events[0].type).toBe('subtitle')
  })

  it('二进制帧与坏 JSON 直接忽略：它们不是我们这个语义层的东西', async () => {
    const ctx = setup()
    ctx.socket.primeTicket('t1')
    void ctx.socket.open()
    ctx.last.accept()
    await Promise.resolve()

    ctx.last.onmessage?.({ data: new ArrayBuffer(4) })
    ctx.last.push('{不是 json')
    expect(ctx.events).toHaveLength(0)
  })
})

describe('断线重连', () => {
  it('断了就按退避重来，而且**每次都重新签一张票**', async () => {
    const ctx = setup({ backoff: [1000, 2000] })
    ctx.socket.primeTicket('t-first')
    void ctx.socket.open()
    ctx.last.accept()
    await Promise.resolve()

    ctx.last.drop(1006)
    expect(ctx.socket.state.value).toBe('reconnecting')
    expect(ctx.socket.attempts.value).toBe(1)
    expect(ctx.clock.delays()).toEqual([1000])

    ctx.clock.fire()
    await Promise.resolve()
    await Promise.resolve()

    // 第二张票是重新签的：断开前那张已经在握手时用掉了
    expect(ctx.ticket).toHaveBeenCalledWith('cs1')
    expect(ctx.sockets).toHaveLength(2)
    expect(ctx.last.url).toContain('ticket=ticket-new')

    ctx.last.accept()
    await Promise.resolve()
    expect(ctx.socket.state.value).toBe('open')
    expect(ctx.socket.attempts.value).toBe(0)
    // 重连与首次进课堂是两件事：页面据此决定要不要重拉历史
    expect(ctx.resumed).toHaveBeenCalledTimes(1)
  })

  it('退避的次数用完了就认输，并且说清接下来怎么办', async () => {
    const ctx = setup({ backoff: [1000, 1000] })
    ctx.socket.primeTicket('t0')
    void ctx.socket.open()
    ctx.last.accept()
    await Promise.resolve()

    ctx.last.drop() // 第 1 次重试
    ctx.clock.fire()
    await Promise.resolve()
    await Promise.resolve()
    ctx.last.drop() // 第 2 次重试
    ctx.clock.fire()
    await Promise.resolve()
    await Promise.resolve()
    ctx.last.drop() // 没得试了

    expect(ctx.socket.state.value).toBe('closed')
    expect(ctx.socket.error.value).toContain('刷新页面')
    expect(ctx.clock.size).toBe(0)
  })

  it('4403 不重试：再签一张票还是同一个人，结论一样', async () => {
    const ctx = setup()
    ctx.socket.primeTicket('t0')
    void ctx.socket.open()
    ctx.last.accept()
    await Promise.resolve()

    ctx.last.drop(CLOSE_FORBIDDEN)

    expect(ctx.socket.state.value).toBe('closed')
    expect(ctx.socket.error.value).toContain('票据')
    expect(ctx.clock.size).toBe(0)
  })

  it('连第一次都没进去（握手被拒，浏览器只给 1006）就退到手翻，不转圈', async () => {
    const ctx = setup()
    ctx.socket.primeTicket('t0')
    void ctx.socket.open()
    ctx.last.drop(1006) // 没 accept 就断了

    expect(ctx.socket.state.value).toBe('closed')
    expect(ctx.socket.error.value).toContain('手动翻页')
    expect(ctx.clock.size).toBe(0)
  })

  it('自己关的不重连', async () => {
    const ctx = setup()
    ctx.socket.primeTicket('t0')
    void ctx.socket.open()
    ctx.last.accept()
    await Promise.resolve()

    ctx.socket.close()
    expect(ctx.last.closed).toBe(CLOSE_NORMAL)
    expect(ctx.socket.state.value).toBe('closed')
    expect(ctx.clock.size).toBe(0)
    expect(ctx.socket.error.value).toBe('')
  })

  it('等退避的时候被关掉：那个定时器也要撤掉，不能到点了又去连', async () => {
    const ctx = setup({ backoff: [5000] })
    ctx.socket.primeTicket('t0')
    void ctx.socket.open()
    ctx.last.accept()
    await Promise.resolve()

    ctx.last.drop()
    expect(ctx.clock.size).toBe(1)

    ctx.socket.close()
    expect(ctx.clock.size).toBe(0)
    expect(ctx.sockets).toHaveLength(1)
  })
})

describe('降级与上行', () => {
  it('disable 之后连都不连：推送通道关着，这一层不该一直转圈', async () => {
    const ctx = setup()
    ctx.socket.disable('这堂课没有推送通道')

    expect(ctx.socket.fallback.value).toBe('这堂课没有推送通道')
    await ctx.socket.open()
    expect(ctx.sockets).toHaveLength(0)
    expect(ctx.socket.fallback.value).not.toBe('')
  })

  it('没连上时的上行静默丢掉并返回 false：课堂的上行都是「此刻的意图」', async () => {
    const ctx = setup()
    expect(ctx.socket.send({ type: 'hand', action: 'raise' })).toBe(false)

    ctx.socket.primeTicket('t0')
    void ctx.socket.open()
    expect(ctx.socket.send({ type: 'hand', action: 'raise' })).toBe(false) // 还没握手
    expect(ctx.last.sent).toHaveLength(0)

    ctx.last.accept()
    await Promise.resolve()
    expect(ctx.socket.send({ type: 'hand', action: 'raise' })).toBe(true)
    expect(ctx.last.last()).toEqual({ type: 'hand', action: 'raise' })
  })

  it('通道断了之后的 send 不抛：onclose 会接手，不在这里重复报错', async () => {
    const ctx = setup()
    ctx.socket.primeTicket('t0')
    void ctx.socket.open()
    ctx.last.accept()
    await Promise.resolve()

    ctx.last.readyState = 3
    expect(ctx.socket.send({ type: 'play' })).toBe(false)
  })
})
