/**
 * 麦克风采集（16k / int16 / 单声道，20ms 一帧）。**P2 实时语音与 P3 课堂共用。**
 *
 * 从 `useRealtimeVoice.ts` 里抽出来，理由只有一个：课堂的语音提问走的是
 * **另一条路**（录一段 PCM → 打成 WAV → `POST /api/voice/asr` → 拿文字去
 * 课堂通道提问），但它开麦那一段与实时语音**一模一样** —— 同样的
 * `getUserMedia`、同样的 AudioWorklet、同样的重采样。两处各写一遍的结果是
 * 两条路的音质、采样率、回声抑制设置慢慢分叉，而症状（「实时那条听得清、
 * 问答这条识别不准」）指向的是上游，不是这里。
 *
 * 交给调用方的是**裸 PCM 帧**：这一层不知道这些帧要去哪里（推给 socket 还是
 * 攒成 WAV），也不该知道。
 *
 * ★ 浏览器侧不出现任何厂商凭据：这里只碰麦克风，不出网。
 */

/** 一帧多少毫秒。上行音频与 WAV 打包都按它切。 */
export const AUDIO_FRAME_MS = 20

/** 采集的采样率。上游 ASR 认 16k，重采样在 worklet 里做（见 `pcm-worklet.js`）。 */
export const CAPTURE_SAMPLE_RATE = 16000

/** 麦克风采集的句柄。 */
export interface Capture {
  stop: () => void
}

/** 开麦。测试注入一个假的（jsdom 里没有 `mediaDevices`）。 */
export type StartCapture = (onChunk: (chunk: ArrayBuffer) => void) => Promise<Capture>

/**
 * 开麦克风并推 PCM。
 *
 * 设备采样率由浏览器的 `AudioContext` 决定（44.1k / 48k 都有），重采样在
 * worklet 里做 —— 主线程上按帧重采样会漏帧，而漏帧在语音识别里就是**丢字**。
 */
export async function startMicrophone(
  onChunk: (chunk: ArrayBuffer) => void,
): Promise<Capture> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  })
  const context = new AudioContext()
  await context.audioWorklet.addModule(new URL('./pcm-worklet.js', import.meta.url))
  const source = context.createMediaStreamSource(stream)
  const node = new AudioWorkletNode(context, 'eduagentx-pcm', {
    processorOptions: {
      targetSampleRate: CAPTURE_SAMPLE_RATE,
      frameSize: (CAPTURE_SAMPLE_RATE * AUDIO_FRAME_MS) / 1000,
    },
  })
  node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => onChunk(event.data)
  source.connect(node)
  // 接一个静音增益再进 destination：worklet 不会自己跑，图上要有出口；
  // 处理器不写输出，所以这条线不会发出声音（也不会引起回声）。
  const mute = context.createGain()
  mute.gain.value = 0
  node.connect(mute)
  mute.connect(context.destination)

  return {
    stop(): void {
      node.port.onmessage = null
      source.disconnect()
      node.disconnect()
      mute.disconnect()
      for (const track of stream.getTracks()) track.stop()
      void context.close()
    },
  }
}

/**
 * 麦克风被拒时该显示哪句话。
 *
 * 「没有权限」与「打不开」在用户那里是两件事：前者他知道去地址栏点一下，
 * 后者得找别的原因。`NotAllowedError` 是浏览器给的那一种明确答复。
 */
export function captureErrorHint(err: unknown): string {
  if (err instanceof Error && err.name === 'NotAllowedError') {
    return '没有麦克风权限；可以在浏览器地址栏里允许后重试，或者直接打字提问。'
  }
  if (err instanceof Error && err.name === 'NotFoundError') {
    return '这台机器上没找到麦克风，直接打字提问吧。'
  }
  return '打不开麦克风，直接打字提问吧。'
}
