/**
 * 实时语音会话（P2 路径 B / F2-6 / F2-7）。
 *
 * 浏览器只跟**自己的 Flask**说话：`/ws/voice/realtime` 是一条原生 WebSocket，
 * 上行二进制帧是麦克风 PCM（16k/int16/单声道），下行是 JSON 文本帧 + 二进制
 * 音频帧交替，用 `seq` 关联。厂商的协议（JSON 里套 Base64 那一套）在
 * 服务端的 Provider 层就转完了 —— **这里不出现任何上游事件名**（P2 §4.2）。
 *
 * 四件事写在这里，因为它们的时机互相纠缠：
 *
 * 1. **按住说话**：`beginTalk()` 采集并推流，`endTalk()` 发
 *    `{type:"audio", final:true}` —— 在 `push_to_talk` 模式下，服务端的 VAD 被
 *    屏蔽，**判停完全由这一条决定**（P2-A18）。忘发它，症状是「按了没反应」。
 * 2. **边说边上屏**：`asr` 的中间结果直接上屏，`final:true` 才定稿。
 * 3. **打断**：教师正在说时学生按下去 → 先**本地**停住回放（乐观 UI，不等
 *    回执），同时发 `barge_in`；收到 `barge_in_ack` 记下延迟。等服务端确认再停
 *    的话，学生已经听了半秒「被自己打断的老师」。
 * 4. **降级**：任何 `error` 都带着服务端给的 `fallback`（P2-B2）。前端**不猜**，
 *    只把那条路对应的话显示出来。
 */

import { computed, onScopeDispose, ref, type Ref } from 'vue'

import { fetchVoiceTicket, realtimeUrl } from '@/api'
import { startMicrophone, type Capture, type StartCapture } from '@/composables/useMicrophone'
import { fallbackHint, fallbackOf } from '@/utils/voice'
import type {
  RealtimeDownlink,
  RealtimeUplink,
  RealtimeUsage,
  VoiceFallback,
} from '@/types/api'

// 采集那一段（`startMicrophone` / `Capture`）住在 `useMicrophone.ts` 里，
// 课堂的语音提问与本模块共用它 —— 两条路的音质、采样率、回声抑制设置
// 必须是同一份，各写一遍会慢慢分叉。这里只是把它再导出一次，好让现有
// 的调用方（`views/CourseView.vue` 等）不用改 import。
export type { Capture, StartCapture } from '@/composables/useMicrophone'

/** 会话状态。`waiting` 是「话已经发出去了，等老师回答」。 */
export type VoiceStatus = 'idle' | 'connecting' | 'ready' | 'listening' | 'waiting' | 'error'

/** 一条落定的问答（消息区里的一对气泡）。 */
export interface VoiceTurn {
  question: string
  reply: string
}

/** WS 的那几个成员。`WebSocket` 结构上满足它，测试可以塞一个假的。 */
export interface SocketLike {
  binaryType: string
  onopen: (() => void) | null
  onclose: (() => void) | null
  onerror: (() => void) | null
  onmessage: ((event: { data: unknown }) => void) | null
  send(data: string | ArrayBufferLike | ArrayBufferView | Blob): void
  close(code?: number): void
}

export interface RealtimeVoiceOptions {
  url?: (ticket: string) => string
  /** 取一张会话票据。默认走 `POST /api/voice/ticket`（P2-F4）。 */
  ticket?: () => Promise<string>
  createSocket?: (url: string) => SocketLike
  /** 开麦克风。默认走 `getUserMedia` + AudioWorklet，测试注入一个假的。 */
  capture?: StartCapture
  /** 播放服务端下来的 PCM。默认走 Web Audio，测试注入一个假的。 */
  createSink?: () => PcmSink
  /** 会话上下文：老师要知道现在上到第几页。 */
  context?: () => { courseId: string; pageNo: number }
  /** 老师开始说话（调用方据此暂停讲稿回放，见「打断」）。 */
  onTeacherSpeaking?: () => void
}

export interface PcmSink {
  push: (frame: ArrayBuffer) => void
  /** 打断：把已经排上队的音频全部撤掉。 */
  reset: () => void
  close: () => void
}

export interface RealtimeVoice {
  status: Ref<VoiceStatus>
  /** 学生正在说的话（`asr` 的中间结果，定稿前一直变） */
  question: Ref<string>
  /** 老师正在说的话（`reply` 逐句累积） */
  reply: Ref<string>
  /** 已经说完的几轮 */
  turns: Ref<VoiceTurn[]>
  error: Ref<string>
  fallback: Ref<VoiceFallback | ''>
  /** 降级提示条上那句话（由 `fallback` 决定，见 utils/voice） */
  hint: Ref<string>
  bargeInMs: Ref<number>
  usage: Ref<RealtimeUsage | null>
  /** 会话建好了没有 —— 「按住说话」要等它为真才有意义 */
  ready: Ref<boolean>
  open: () => Promise<void>
  /**
   * 开始采集。**返回真的采上了没有**：建连失败、麦克风被拒都返回 false。
   *
   * 调用方要这个返回值才能把按钮摆回原样 —— 只看 `error` 的话，「按住说话」
   * 的按下状态会一直亮着，而实际上什么都没在录。
   */
  beginTalk: () => Promise<boolean>
  endTalk: () => void
  interrupt: () => void
  close: () => void
}

/**
 * 服务端在信封里写的那句话（「语音功能已关闭」「请先选择音色」…）。
 *
 * 取服务端的原文而不是在这里另写一句：同一件事（比如开关关着）在设置页、
 * 试听、这里三处出现，各写一句的结果是三句话慢慢分叉。取不到就退回
 * 调用方给的那句 —— 网络层失败没有 message 可读。
 */
function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback
}

export function useRealtimeVoice(options: RealtimeVoiceOptions = {}): RealtimeVoice {
  // 地址**到建连那一刻才取**：课堂页没开麦克风时（纯文字听课、或者这节课压根没配语音）
  // 这条会话不该被碰一下 —— 一个永远用不到的依赖在挂载时就报错，会让整页白掉。
  // 票据一次一张（用过即废），所以地址得等取到票之后再拼 —— 见 `open()`。
  const url = options.url ?? ((ticket: string) => realtimeUrl(ticket))
  const createSocket = options.createSocket ?? ((target: string) => new WebSocket(target) as unknown as SocketLike)
  const createSink = options.createSink ?? (() => createAudioSink())
  const fetchTicket =
    options.ticket ?? (async () => (await fetchVoiceTicket()).ticket)

  const status = ref<VoiceStatus>('idle')
  const question = ref('')
  const reply = ref('')
  const turns = ref<VoiceTurn[]>([])
  const error = ref('')
  const fallback = ref<VoiceFallback | ''>('')
  const bargeInMs = ref(0)
  const usage = ref<RealtimeUsage | null>(null)
  const ready = ref(false)
  const hint = computed(() => (fallback.value ? fallbackHint(fallback.value) : ''))

  let socket: SocketLike | null = null
  let capture: Capture | null = null
  let sink: PcmSink | null = null
  let seq = 0

  function send(message: RealtimeUplink): void {
    if (!socket) return
    try {
      socket.send(JSON.stringify(message))
    } catch {
      // 通道已经断了：下面的 onclose 会把它收拾干净，这里不重复报错
    }
  }

  async function open(): Promise<void> {
    if (socket) return
    status.value = 'connecting'
    error.value = ''
    fallback.value = ''
    sink = createSink()

    // 先取票（P2-F4），再建连。**不能省成一次裸连**：开关关着（40302）、
    // 上游没配好（40201）都在这趟 HTTP 里说清楚了，直接连 WS 的话这些原因
    // 会塌成浏览器的一句「连接失败」，而学生要的答案是「为什么、现在怎么办」。
    // 每种 open 都重新取一张 —— 票据用过即废，缓存下来的第二张开不了门。
    let ticket: string
    try {
      ticket = await fetchTicket()
    } catch (err) {
      sink.close()
      sink = null
      fail(messageOf(err, '语音暂时不可用，已切换为文字问答'), fallbackOf(err) || 'text')
      return
    }

    await new Promise<void>((resolve) => {
      const channel = createSocket(url(ticket))
      socket = channel
      channel.binaryType = 'arraybuffer'
      channel.onopen = () => {
        // 建连即开会话：`ready` 回来才算真的能用（P2 §4.2 的映射表）
        send({
          type: 'start',
          mode: 'voice_chat',
          context: options.context?.() ?? {},
        })
      }
      channel.onmessage = (event) => {
        if (typeof event.data === 'string') {
          onMessage(event.data)
          // 建好了、或者服务端明确说了不行 —— 两种都算「这次 open 有结论了」，
          // 不能只等 ready：会话建不起来时 error 才是唯一会来的那一帧。
          if (ready.value || status.value === 'error') resolve()
          return
        }
        // 二进制帧 = 音频。前面那条 `{type:"audio",seq}` 只是「下一帧是音频」的提示
        if (event.data instanceof ArrayBuffer) sink?.push(event.data)
      }
      channel.onerror = () => {
        // 浏览器不给细节（安全考虑），能给的一句话就是这个
        fail('连接实时语音失败，已切换为文字问答', 'text')
        resolve()
      }
      channel.onclose = () => {
        socket = null
        ready.value = false
        if (status.value !== 'error') status.value = 'idle'
        resolve()
      }
      // 连不上时 onclose/onerror 会来收尾，这里不设超时：
      // 一个「15 秒后自己放弃」的计时器在慢网络下会把本来能成的会话掐断。
    })
    if (ready.value) status.value = 'ready'
  }

  function onMessage(raw: string): void {
    let payload: RealtimeDownlink
    try {
      payload = JSON.parse(raw) as RealtimeDownlink
    } catch {
      return // 不认识的帧直接忽略：它不是我们这个语义层的东西
    }
    switch (payload.type) {
      case 'ready':
        ready.value = true
        status.value = 'ready'
        break
      case 'asr':
        question.value = payload.text
        if (payload.final) status.value = 'waiting'
        break
      case 'reply':
        reply.value = payload.text
        status.value = 'waiting'
        options.onTeacherSpeaking?.()
        break
      case 'audio':
        // 音频本体是紧随其后的二进制帧，这里没有别的动作
        break
      case 'barge_in_ack':
        bargeInMs.value = payload.latencyMs
        break
      case 'barge_in':
        // 服务端主动打断（上游识别到学生插话）：本地立刻停住
        sink?.reset()
        break
      case 'done':
        usage.value = payload.usage
        settle()
        break
      case 'usage':
        usage.value = payload.usage
        break
      case 'closed':
        ready.value = false
        status.value = 'idle'
        break
      case 'error':
        fail(payload.message, payload.fallback, payload.code)
        break
      default:
        break
    }
  }

  /** 一轮结束：把问答落进消息区，清掉「正在说」的两行。 */
  function settle(): void {
    const asked = question.value.trim()
    const answered = reply.value.trim()
    if (asked || answered) turns.value = [...turns.value, { question: asked, reply: answered }]
    question.value = ''
    reply.value = ''
    status.value = ready.value ? 'ready' : 'idle'
  }

  function fail(message: string, path: VoiceFallback, code = ''): void {
    error.value = message
    fallback.value = path
    status.value = 'error'
    if (code) console.warn('[voice] 实时语音错误', code, message)
  }

  async function beginTalk(): Promise<boolean> {
    await open()
    if (!ready.value) return false // 没建起来：降级提示条已经在上面显示原因了
    if (capture) return true
    question.value = ''
    const startCapture = options.capture ?? startMicrophone
    try {
      capture = await startCapture((chunk) => {
        // 先发「后面这一帧是音频」的提示，再发二进制帧（P2 §4.2 的 wire 格式）
        seq += 1
        send({ type: 'audio', seq })
        if (socket) socket.send(chunk)
      })
      status.value = 'listening'
      return true
    } catch (err) {
      // 麦克风被拒绝是最常见的一种：说清是权限问题，别让人以为是语音坏了
      fail(
        err instanceof Error && err.name === 'NotAllowedError'
          ? '没有麦克风权限，无法语音提问；可以在浏览器地址栏里允许后重试'
          : '打不开麦克风，已切换为文字问答',
        'text',
      )
      return false
    }
  }

  function endTalk(): void {
    capture?.stop()
    capture = null
    if (status.value === 'listening') status.value = 'waiting'
    // 松开按键 = 强制判停。这条不发，服务端永远等不到「说完了」
    send({ type: 'audio', final: true })
  }

  function interrupt(): void {
    sink?.reset()
    send({ type: 'barge_in' })
    if (status.value === 'listening') status.value = 'ready'
  }

  function close(): void {
    send({ type: 'stop' })
    capture?.stop()
    capture = null
    sink?.close()
    sink = null
    socket?.close()
    socket = null
    ready.value = false
    status.value = 'idle'
  }

  onScopeDispose(close)

  return {
    status,
    question,
    reply,
    turns,
    error,
    fallback,
    hint,
    bargeInMs,
    usage,
    ready,
    open,
    beginTalk,
    endTalk,
    interrupt,
    close,
  }
}

// --- 浏览器实现（测试注入替身，这两段不会被走到）---

/** 默认的 PCM 播放：Web Audio 排队播，`reset()` 一次性撤掉。 */
export function createAudioSink(sampleRate = 16000): PcmSink {
  const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  const context = new Ctx!()
  const gain = context.createGain()
  gain.connect(context.destination)
  const live = new Set<AudioBufferSourceNode>()
  let nextAt = 0

  return {
    push(frame: ArrayBuffer): void {
      const samples = new Int16Array(frame)
      if (!samples.length) return
      const buffer = context.createBuffer(1, samples.length, sampleRate)
      const channel = buffer.getChannelData(0)
      for (let i = 0; i < samples.length; i += 1) channel[i] = samples[i] / 32768
      const source = context.createBufferSource()
      source.buffer = buffer
      source.connect(gain)
      const at = Math.max(context.currentTime, nextAt)
      source.start(at)
      nextAt = at + buffer.duration
      live.add(source)
      source.onended = () => live.delete(source)
    },
    reset(): void {
      for (const source of live) {
        try {
          source.stop()
        } catch {
          // 已经播完的自然停：停不了也不影响，它马上就结束了
        }
      }
      live.clear()
      nextAt = 0
    },
    close(): void {
      this.reset()
      void context.close()
    },
  }
}

