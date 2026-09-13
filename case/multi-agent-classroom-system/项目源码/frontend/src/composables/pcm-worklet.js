/**
 * 麦克风 PCM 采集（AudioWorkletProcessor，P2-A8 / F2-7）。
 *
 * 浏览器给的永远是**32 位浮点、设备采样率**（通常是 48k）；上游要的是
 * **16k / int16 / 单声道 / 20ms 一包**。转换就在这里一次做完：
 * 放在主线程做，每 20ms 一包、每包都要过一遍 JS —— 那是典型的
 * 「音频线程在等主线程」，表现是推流忽快忽慢，上游那边听起来是断断续续。
 *
 * 这里是 **worklet 全局作用域**：没有 window / document，
 * 也不能 import，`sampleRate` 是它自带的全局量。
 */

class PCMProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const config = (options && options.processorOptions) || {}
    this.targetRate = config.targetSampleRate || 16000
    this.frameSize = config.frameSize || 640 // 20ms @ 16k
    // 源采样率 / 目标采样率：每采一个目标样本，源波形上要往前爬这么远
    this.ratio = sampleRate / this.targetRate
    this.buffer = new Int16Array(this.frameSize)
    this.offset = 0
    this.readPos = 0
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true

    while (this.readPos < channel.length) {
      // 线性插值重采样。上游按 16k 解析，喂 48k 进去听到的是快放三倍的怪声
      const index = Math.floor(this.readPos)
      const frac = this.readPos - index
      const first = channel[index] === undefined ? 0 : channel[index]
      const second = channel[index + 1] === undefined ? first : channel[index + 1]
      const sample = first + (second - first) * frac
      const clamped = Math.max(-1, Math.min(1, sample))
      this.buffer[this.offset] = Math.round(clamped * 32767)
      this.offset += 1
      if (this.offset >= this.frameSize) {
        // 拷贝一份再交出去：这块内存下一轮还要接着写
        const chunk = this.buffer.slice(0)
        this.port.postMessage(chunk.buffer, [chunk.buffer])
        this.offset = 0
      }
      this.readPos += this.ratio
    }
    this.readPos -= channel.length
    return true
  }
}

registerProcessor('eduagentx-pcm', PCMProcessor)
