/**
 * 实时语音会话（P2-A7 / P2-A8 / P2-A9 / P2-B1 / §4.2）。
 *
 * 往上，浏览器只跟自己的 Flask 说话；往下，它只认我们自己的那套事件名。
 * **上游的事件名一个都不许出现在这条路上**（P2 §4.2），所以这里的替身
 * 也按我们自己的协议说话 —— 谁要是把 `response.audio.delta` 这类名字
 * 抄进前端，这个文件的替身就对不上了。
 *
 * 另外三件事在这里钉住：
 * 1. **松开按键必须发 `{type:"audio",final:true}`**：`push_to_talk` 模式下
 *    服务端的 VAD 被屏蔽，判停完全由这一条决定（P2-A18）。忘发的症状是
 *    「按住说了半天没反应」。
 * 2. **打断是乐观的**：本地先停回放，再发 `barge_in`。等回执再停，学生
 *    已经听了半秒「被自己打断的老师」（P2-A8）。
 * 3. **降级路径由服务端给**：前端只把 `fallback` 那条路对应的话显示出来。
 */

import { effectScope } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  useRealtimeVoice,
  type Capture,
  type PcmSink,
  type RealtimeVoice,
  type SocketLike,
} from '@/composables/useRealtimeVoice'

/** 一个假 WS：发出去的东西都记下来，收到的帧由测试手动喂。 */
class FakeSocket implements SocketLike {
  binaryType = 'blob'
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null

  sent: (string | ArrayBufferLike | ArrayBufferView | Blob)[] = []
  closed = false
  url: string

  constructor(url: string) {
    this.url = url
  }

  send(data: string | ArrayBufferLike | ArrayBufferView | Blob): void {
    this.sent.push(data)
  }

  close(): void {
    this.closed = true
  }

  /** 上行的 JSON 帧（二进制帧不在这里）。 */
  get json(): Record<string, unknown>[] {
    return this.sent
      .filter((item): item is string => typeof item === 'string')
      .map((item) => JSON.parse(item) as Record<string, unknown>)
  }

  /** 喂一帧 JSON 给前端。 */
  emit(payload: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }

  /** 喂一帧音频（上行那条协议里，它前面总跟着一条 `{type:"audio",seq}`）。 */
  emitAudio(bytes: number[] = [1, 2]): void {
    this.onmessage?.({ data: new Uint8Array(bytes).buffer })
  }
}

function makeRig(
  options: { capture?: Capture; failCapture?: Error; failTicket?: Error } = {},
) {
  const socket = new FakeSocket('ws://localhost/ws/voice/realtime')
  const frames: ArrayBuffer[] = []
  const sink: PcmSink = {
    push: (frame) => frames.push(frame),
    reset: vi.fn(),
    close: vi.fn(),
  }
  const chunks: ((chunk: ArrayBuffer) => void)[] = []
  const capture: Capture = options.capture ?? { stop: vi.fn() }
  const onTeacherSpeaking = vi.fn()
  /** 每次建连取了哪些票 —— 票据用过即废，重连必须再取一张（P2-F4）。 */
  const tickets: string[] = []

  const scope = effectScope()
  const voice = scope.run(() =>
    useRealtimeVoice({
      // 地址带上票据：服务端没票不开门，所以真地址一定要有它
      url: (ticket) => `${socket.url}?ticket=${ticket}`,
      ticket: async () => {
        if (options.failTicket) throw options.failTicket
        const ticket = `t-${tickets.length + 1}`
        tickets.push(ticket)
        return ticket
      },
      createSocket: (target) => {
        socket.url = target
        return socket
      },
      createSink: () => sink,
      context: () => ({ courseId: 'c1', pageNo: 3 }),
      onTeacherSpeaking,
      capture: async (onChunk) => {
        if (options.failCapture) throw options.failCapture
        chunks.push(onChunk)
        return capture
      },
    }),
  ) as RealtimeVoice

  return { voice, socket, sink, frames, chunks, capture, onTeacherSpeaking, tickets, scope }
}

const scopes: ReturnType<typeof effectScope>[] = []

function rig(options: { capture?: Capture; failCapture?: Error; failTicket?: Error } = {}) {
  const made = makeRig(options)
  scopes.push(made.scope)
  return made
}

/**
 * 等 `open()` 走到建连那一步。
 *
 * `open()` 现在**先取票再建连**（P2-F4），socket 与它的回调是取到票之后才有的：
 * 调用方 `await open()` 之前先 `onopen?.()` 的话，那个回调还是 null，什么都没发生 ——
 * 症状是 `await opening` 挂到超时。用宏任务而不是数微任务：微任务的条数会随
 * 实现里的 `await` 个数变化，而这里要等的只是一次「票回来了」。
 */
const settled = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

/** 建好会话的最小路径：open() → 服务端回 ready。 */
async function ready(options: { capture?: Capture; failCapture?: Error; failTicket?: Error } = {}) {
  const made = rig(options)
  const opening = made.voice.open()
  await settled()
  made.socket.onopen?.()
  made.socket.emit({ type: 'ready', sessionId: 's1', sampleRate: 16000 })
  await opening
  return made
}

afterEach(() => {
  for (const scope of scopes.splice(0)) scope.stop()
})

describe('建连与会话建立', () => {
  it('连上就发 start，带上模式与当前页', async () => {
    const made = await ready()

    expect(made.socket.json[0]).toEqual({
      type: 'start',
      mode: 'voice_chat',
      context: { courseId: 'c1', pageNo: 3 },
    })
    expect(made.voice.ready.value).toBe(true)
    expect(made.voice.status.value).toBe('ready')
  })

  it('服务端说不行时 open() 也要有结论（不能一直挂着）', async () => {
    const made = rig()
    const opening = made.voice.open()
    await settled()
    made.socket.onopen?.()
    made.socket.emit({ type: 'error', code: 'REALTIME_FAILED', message: '连不上', fallback: 'text' })

    await opening // 不 resolve 的话这一行会超时 —— 那正是要防的 bug

    expect(made.voice.status.value).toBe('error')
    expect(made.voice.ready.value).toBe(false)
  })

  it('连不上时给出降级那句话（来自服务端的 fallback，不是我们自己猜的）', async () => {
    const made = rig()
    const opening = made.voice.open()
    await settled()
    made.socket.onerror?.()
    await opening

    expect(made.voice.fallback.value).toBe('text')
    expect(made.voice.hint.value).toContain('文字问答')
  })

  it('建连之前先取票（P2-F4）：地址上带着它，没票不开门', async () => {
    const made = await ready()

    expect(made.tickets).toEqual(['t-1'])
    expect(made.socket.url).toBe('ws://localhost/ws/voice/realtime?ticket=t-1')
  })

  it('票据取不到也要说清原因，而不是去撞一次注定失败的握手', async () => {
    const made = rig({
      failTicket: Object.assign(new Error('语音功能已关闭'), { code: 40302 }),
    })

    await made.voice.open()

    expect(made.socket.sent).toEqual([]) // 一条握手都没发起
    expect(made.voice.status.value).toBe('error')
    expect(made.voice.error.value).toBe('语音功能已关闭')
    expect(made.voice.hint.value).toContain('文字问答')
  })

  it('重连要重新取票：票据用过即废，缓存下来的第二张开不了门', async () => {
    const made = await ready()

    made.socket.onclose?.() // 掉线
    const opening = made.voice.open()
    await settled()
    made.socket.onopen?.()
    made.socket.emit({ type: 'ready', sessionId: 's2', sampleRate: 16000 })
    await opening

    expect(made.tickets).toEqual(['t-1', 't-2'])
    expect(made.socket.url).toContain('ticket=t-2')
  })
})

describe('一轮问答（P2-A7）', () => {
  it('识别结果边说边上屏，定稿后才进「等回答」', async () => {
    const made = await ready()
    await made.voice.beginTalk()
    expect(made.voice.status.value).toBe('listening')

    // 中间结果只改文字：**状态说的还是「正在采音」**，不能因为上游回了个中间
    // 结果就把麦克风按钮说成「说完了」
    made.socket.emit({ type: 'asr', text: '学习率', final: false })
    expect(made.voice.question.value).toBe('学习率')
    expect(made.voice.status.value).toBe('listening')

    made.socket.emit({ type: 'asr', text: '学习率为什么要衰减', final: true })
    expect(made.voice.question.value).toBe('学习率为什么要衰减')
    expect(made.voice.status.value).toBe('waiting')
  })

  it('老师开口时通知调用方（课堂据此把讲稿停下）', async () => {
    const made = await ready()

    made.socket.emit({ type: 'reply', text: '因为越接近谷底，步子该越小。' })

    expect(made.voice.reply.value).toBe('因为越接近谷底，步子该越小。')
    expect(made.onTeacherSpeaking).toHaveBeenCalled()
  })

  it('一轮结束后落到消息区，问答两行都清空', async () => {
    const made = await ready()

    made.socket.emit({ type: 'asr', text: '学习率为什么要衰减', final: true })
    made.socket.emit({ type: 'reply', text: '因为越接近谷底，步子该越小。' })
    made.socket.emit({
      type: 'done',
      usage: { durationMs: 4200, asrChars: 9, replyChars: 16, firstFrameMs: 700 },
    })

    expect(made.voice.turns.value).toEqual([
      { question: '学习率为什么要衰减', reply: '因为越接近谷底，步子该越小。' },
    ])
    expect(made.voice.question.value).toBe('')
    expect(made.voice.reply.value).toBe('')
    expect(made.voice.status.value).toBe('ready')
    expect(made.voice.usage.value?.firstFrameMs).toBe(700)
  })

  it('音频帧进播放队列，前面的 seq 只是提示', async () => {
    const made = await ready()

    made.socket.emit({ type: 'audio', seq: 1 })
    made.socket.emitAudio([1, 2, 3])

    expect(made.frames).toHaveLength(1)
    expect(new Uint8Array(made.frames[0])).toEqual(new Uint8Array([1, 2, 3]))
  })

  it('服务端主动打断时把已排队的音频撤掉（学生插话）', async () => {
    const made = await ready()

    made.socket.emit({ type: 'barge_in' })
    expect(made.sink.reset).toHaveBeenCalled()
  })
})

describe('按住说话（P2-A18）', () => {
  it('采集到的每一包先发 seq 再发二进制', async () => {
    const made = await ready()

    await made.voice.beginTalk()
    expect(made.voice.status.value).toBe('listening')

    made.chunks[0](new Uint8Array([9, 9]).buffer)

    expect(made.socket.json.at(-1)).toEqual({ type: 'audio', seq: 1 })
    const binaryFrames = made.socket.sent.filter((item) => item instanceof ArrayBuffer)
    expect(binaryFrames).toHaveLength(1)
  })

  it('松开发 final —— push_to_talk 模式下判停完全靠这一条', async () => {
    const made = await ready()
    await made.voice.beginTalk()

    made.voice.endTalk()

    expect(made.socket.json.at(-1)).toEqual({ type: 'audio', final: true })
    expect(made.capture.stop).toHaveBeenCalled()
    expect(made.voice.status.value).toBe('waiting')
  })

  it('一包都没采到也要发 final（说了半句就松手是常事）', async () => {
    const made = await ready()
    await made.voice.beginTalk()

    made.voice.endTalk()

    expect(made.socket.json.at(-1)).toEqual({ type: 'audio', final: true })
  })

  it('麦克风被拒绝时说清是权限问题，并给出文字降级', async () => {
    const denied = new Error('denied')
    denied.name = 'NotAllowedError'
    const made = await ready({ failCapture: denied })

    // 返回值是调用方唯一的「到底采上了没有」：界面靠它把按下状态收回去，
    // 不然按钮会一直亮着「松开发送」，而其实什么都没在录
    expect(await made.voice.beginTalk()).toBe(false)
    expect(made.voice.status.value).toBe('error')
    expect(made.voice.error.value).toContain('麦克风权限')
    expect(made.voice.hint.value).toContain('文字问答')
  })

  it('采上了才算数', async () => {
    const made = await ready()
    expect(await made.voice.beginTalk()).toBe(true)
  })
})

describe('打断（P2-A8）', () => {
  it('先本地停住再发 barge_in（不等回执）', async () => {
    const made = await ready()
    await made.voice.beginTalk()
    made.socket.emit({ type: 'reply', text: '因为……' })

    made.voice.interrupt()

    expect(made.sink.reset).toHaveBeenCalled()
    expect(made.socket.json.at(-1)).toEqual({ type: 'barge_in' })
  })

  it('回执里的延迟记下来（用于确认 ≤300ms）', async () => {
    const made = await ready()

    made.socket.emit({ type: 'barge_in_ack', latencyMs: 180 })

    expect(made.voice.bargeInMs.value).toBe(180)
  })
})

describe('收尾', () => {
  it('close 发 stop 并断开；作用域停掉时也会收', async () => {
    const made = await ready()

    made.voice.close()

    expect(made.socket.json.at(-1)).toEqual({ type: 'stop' })
    expect(made.socket.closed).toBe(true)
    expect(made.voice.ready.value).toBe(false)
  })

  it('不认识的帧直接忽略（协议以后加东西不该把前端弄挂）', async () => {
    const made = await ready()

    made.socket.emit({ type: 'something_new', value: 1 })

    expect(made.voice.status.value).toBe('ready')
  })

  it('不是 JSON 的文本帧也忽略', async () => {
    const made = await ready()

    made.socket.onmessage?.({ data: '不是 json' })

    expect(made.voice.status.value).toBe('ready')
  })
})
