/**
 * 录一段语音提问（P3-A5 的学生提问）。
 *
 * **为什么不去走 P2 那条实时语音通道**：那条路是「边说边传、上游边说边认、
 * 老师同时回答」——它回答完就把答案显示在语音面板上，而课堂上真正的答案
 * 只能有一个（`runtime._answer` 那条），否则同一句话会有两个版本，一个进
 * 消息流与课堂记录、一个不进。所以课堂的提问改成：**录一段 → 识别出文字 →
 * 学生确认 → 走课堂通道发 `ask`**。代价是多等一下识别，换来的是「记录里
 * 的那句话就是我问的那句话」。
 *
 * 走 `POST /api/voice/asr` 而不是自己拼实时协议，是因为后端的 docstring
 * 明确把这条路列为正路（`app/api/voice.py`）：
 *
 * > 前端要么录 PCM（AudioWorklet），要么走实时语音那条路。
 *
 * 而且它**明确拒绝 webm/opus**（回 40001）：`MediaRecorder` 的默认产物在这个
 * 后端上是不认的，所以这里必须自己把 PCM 打成 WAV —— 这也正是本模块存在的
 * 全部理由。**别把这里换成 `MediaRecorder`**，症状是「录了、发了、40001」。
 *
 * 采集复用 `useMicrophone`（与实时语音同一份重采样），这一层只管攒帧、
 * 打 WAV、发出去。
 */

import { onScopeDispose, ref, type Ref } from 'vue'

import { transcribeAudio } from '@/api'
import {
  AUDIO_FRAME_MS,
  CAPTURE_SAMPLE_RATE,
  captureErrorHint,
  startMicrophone,
  type Capture,
  type StartCapture,
} from '@/composables/useMicrophone'

/**
 * 一次最多录多久（毫秒）。到点自动收工。
 *
 * 不是为了省事：PCM 是**攒在内存里**的（16k × 2 字节 × 每秒 = 32KB/s），
 * 忘松开按键就会一直涨；而一次提问说到 60 秒早就该停下来想想了。
 * 到点自动停比弹一句「你录太久了」好 —— 后者还要用户再点一次。
 */
export const MAX_RECORD_MS = 60_000

/** WAV 头长度（16 位单声道那一套）。解码端按它跳过头部。 */
export const WAV_HEADER_BYTES = 44

export interface VoiceRecorderOptions {
  /** 采集。测试注入一个假的。 */
  capture?: StartCapture
  /** 识别。默认走 `POST /api/voice/asr`。 */
  transcribe?: (blob: Blob, filename: string) => Promise<string>
  /** 自动收工时的回调（页面据此把按钮摆回原样）。 */
  onAutoStop?: () => void
}

export interface VoiceRecorder {
  recording: Ref<boolean>
  /** 已经录了多久（毫秒）。提问条上那个计时器。 */
  elapsedMs: Ref<number>
  /** 识别出来的文字。空串 = 还没识别 / 没听清。 */
  text: Ref<string>
  /** 上一次的错误（麦克风被拒、识别失败…）。空串表示没出错。 */
  error: Ref<string>
  busy: Ref<boolean>
  start: () => Promise<boolean>
  /** 收工并识别。返回识别出来的文字（失败返回空串，`error` 里有原因）。 */
  stop: () => Promise<string>
  /** 放弃这一段（不识别、不发）。 */
  cancel: () => void
}

/**
 * 把一串 PCM 帧打成 WAV（16 位 / 单声道）。
 *
 * 自己拼 44 字节的头，是因为上游只认 WAV：`MediaRecorder` 出的 webm/opus
 * 在这个后端上会被 40001 挡回来。**头里的字段一个都不能省** —— 少一个
 * 字节序或者 `byteRate` 写错，得到的是「后端说格式不认」而不是「声音难听」。
 */
export function encodeWav(chunks: ArrayBuffer[], sampleRate = CAPTURE_SAMPLE_RATE): Blob {
  const dataBytes = chunks.reduce((total, chunk) => total + chunk.byteLength, 0)
  const buffer = new ArrayBuffer(WAV_HEADER_BYTES + dataBytes)
  const view = new DataView(buffer)
  const bytesPerSample = 2

  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataBytes, true) // 后面还剩多少字节
  writeAscii(view, 8, 'WAVE')
  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true) // fmt 块固定 16 字节
  view.setUint16(20, 1, true) // 1 = PCM，没有压缩
  view.setUint16(22, 1, true) // 单声道
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * bytesPerSample, true) // byteRate
  view.setUint16(32, bytesPerSample, true) // blockAlign
  view.setUint16(34, 8 * bytesPerSample, true) // bitsPerSample
  writeAscii(view, 36, 'data')
  view.setUint32(40, dataBytes, true)

  const out = new Uint8Array(buffer)
  let offset = WAV_HEADER_BYTES
  for (const chunk of chunks) {
    out.set(new Uint8Array(chunk), offset)
    offset += chunk.byteLength
  }
  return new Blob([out], { type: 'audio/wav' })
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i))
}

export function useVoiceRecorder(options: VoiceRecorderOptions = {}): VoiceRecorder {
  const startCapture = options.capture ?? startMicrophone
  const transcribe =
    options.transcribe ??
    (async (blob: Blob, filename: string) => (await transcribeAudio(blob, filename)).text)

  const recording = ref(false)
  const elapsedMs = ref(0)
  const text = ref('')
  const error = ref('')
  const busy = ref(false)

  let capture: Capture | null = null
  let chunks: ArrayBuffer[] = []
  let ticker: ReturnType<typeof setInterval> | null = null
  let startedAt = 0
  let autoStop: ReturnType<typeof setTimeout> | null = null

  function tidy(): void {
    capture?.stop()
    capture = null
    if (ticker !== null) {
      clearInterval(ticker)
      ticker = null
    }
    if (autoStop !== null) {
      clearTimeout(autoStop)
      autoStop = null
    }
    recording.value = false
  }

  async function start(): Promise<boolean> {
    if (recording.value || busy.value) return false
    error.value = ''
    text.value = ''
    chunks = []
    try {
      capture = await startCapture((chunk) => {
        chunks.push(chunk)
        // 帧数就是时长：一帧固定 20ms，不用另外记开始时刻（设备抖动也影响不了它）
        elapsedMs.value = chunks.length * AUDIO_FRAME_MS
      })
    } catch (err) {
      capture = null
      error.value = captureErrorHint(err)
      return false
    }
    recording.value = true
    elapsedMs.value = 0
    startedAt = Date.now()
    ticker = setInterval(() => {
      elapsedMs.value = Date.now() - startedAt
    }, 200)
    autoStop = setTimeout(() => {
      // 到点自动收工。**不静默丢弃**：录到的东西照样送去识别，
      // 只是把按钮摆回来（`onAutoStop`），免得学生以为还能继续说
      options.onAutoStop?.()
    }, MAX_RECORD_MS)
    return true
  }

  async function stop(): Promise<string> {
    if (!recording.value && !chunks.length) return ''
    tidy()
    const recorded = chunks
    chunks = []
    if (!recorded.length) {
      error.value = '这一段没录到声音，再试一次或者直接打字提问。'
      return ''
    }
    busy.value = true
    try {
      const said = await transcribe(encodeWav(recorded), 'ask.wav')
      text.value = String(said ?? '').trim()
      return text.value
    } catch (err) {
      error.value =
        err instanceof Error && err.message ? err.message : '识别失败，请直接打字提问。'
      return ''
    } finally {
      busy.value = false
    }
  }

  function cancel(): void {
    tidy()
    chunks = []
    elapsedMs.value = 0
  }

  onScopeDispose(tidy)

  return { recording, elapsedMs, text, error, busy, start, stop, cancel }
}
