/**
 * 课堂讲稿播放器（P2 §6 的 `useNarrationPlayer`，F2-5）。
 *
 * 输入只有一份：`audio-manifest` 的 beat 队列。播放器**不自己拼 URL、
 * 不自己判断有没有声音** —— 清单里 `url` 是空串就是没得播，这一点在服务端
 * 已经判完了（音色、服务商、开关三件事的合取），前端再判一次只会多一处分叉。
 *
 * 三条口径：
 *
 * 1. **一句一句播，播完自动下一句**。跨页也照走（第 3 页最后一句播完接第 4 页
 *    第一句），页面跟着 beat 走由调用方 `watch(index)` 决定 —— 播放器不知道
 *    「页」是什么东西。
 * 2. **没有音频也有节奏**。这一句合成不出来时（`url` 为空）按 `estSec` 走一个
 *    计时器：字幕照样按讲稿推进，课堂不会卡在第一句。这正是 P2-A3 说的
 *    「降级时按整句切换，误差 ≤ 300ms」—— 计时器的误差就是这一档的误差。
 * 3. **位置只有一个来源**。定时读 `audio.currentTime` / 自己计时，**不挂
 *    `timeupdate` 之类的监听**：两套位置来源在切句、拖动、barge-in 三种时刻
 *    会对不上，而那种 bug 表现为「字幕慢半拍」这种说不清的症状。
 *
 * 可测试性：音频元素与时钟都可注入（`createAudio` / `now`）。jsdom 里
 * `HTMLMediaElement.play()` 是未实现的，硬用真元素会让每个用例都要打桩
 * 一堆原型方法；注入一个假的，断言就落在「src 换没换、播没播、位置对不对」
 * 这三件真事上。
 */

import { computed, onScopeDispose, ref, type Ref } from 'vue'

import { beatDurationMs } from '@/utils/voice'
import type { AudioBeat } from '@/types/api'

/** 位置刷新间隔。P2-A3 要求高亮误差 ≤150ms，留一半余量给渲染。 */
const TICK_MS = 60

/** 倍速档位（F2-5：1.0~2.0）。 */
export const RATES = [1.0, 1.25, 1.5, 2.0] as const

/** 播放器要用到的那几个成员。`HTMLAudioElement` 结构上就满足它。 */
export interface AudioLike {
  src: string
  currentTime: number
  playbackRate: number
  paused: boolean
  ended: boolean
  play(): Promise<void> | void
  pause(): void
}

export interface NarrationPlayerOptions {
  /** 造一个音频元素。默认 `new Audio()`（jsdom 里也可用，只是 play 不发声）。 */
  createAudio?: () => AudioLike
  /** 时钟。默认 `performance.now()`（毫秒）。测试注入一个可推进的假钟。 */
  now?: () => number
  /** 播完最后一句怎么办：默认停下并停在最后一句上。 */
  onEnd?: () => void
}

export interface NarrationPlayer {
  beats: Ref<AudioBeat[]>
  index: Ref<number>
  playing: Ref<boolean>
  /** 当前这一句内的位置（毫秒） */
  positionMs: Ref<number>
  rate: Ref<number>
  error: Ref<string>
  current: Ref<AudioBeat | null>
  /** 整课总时长。没有音频的句子按 `estSec` 估，所以它可能是**约数** */
  totalMs: Ref<number>
  /** 整课已播到的位置（前面几句之和 + 当前句内的位置） */
  elapsedMs: Ref<number>
  /** 总时长里有没有估算成分（有没有哪一句没音频）。界面据此显示「约」 */
  estimated: Ref<boolean>
  /** 队列里有几句是有声音的（0 就是整节课静音，播放键该说明原因） */
  playableCount: Ref<number>
  load: (beats: AudioBeat[], options?: { keepPosition?: boolean }) => void
  play: () => Promise<void>
  pause: () => void
  toggle: () => Promise<void>
  stop: () => void
  goTo: (nextIndex: number) => Promise<void>
  next: () => Promise<void>
  prev: () => Promise<void>
  /** 拖动进度条：按整课比例跳到对应的一句（F2-5 的「跳到指定页」）。 */
  seekRatio: (ratio: number) => Promise<void>
  setRate: (value: number) => void
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

export function useNarrationPlayer(options: NarrationPlayerOptions = {}): NarrationPlayer {
  const createAudio = options.createAudio ?? (() => new Audio() as unknown as AudioLike)
  const now = options.now ?? (() => performance.now())

  const audio = createAudio()

  const beats = ref<AudioBeat[]>([])
  const index = ref(0)
  const playing = ref(false)
  const positionMs = ref(0)
  const rate = ref(1)
  const error = ref('')

  const current = computed<AudioBeat | null>(() => beats.value[index.value] ?? null)
  const playableCount = computed(() => beats.value.filter((beat) => Boolean(beat.url)).length)
  const totalMs = computed(() =>
    beats.value.reduce((sum, beat) => sum + beatDurationMs(beat), 0),
  )
  const elapsedMs = computed(
    () =>
      beats.value
        .slice(0, index.value)
        .reduce((sum, beat) => sum + beatDurationMs(beat), 0) + positionMs.value,
  )
  const estimated = computed(() => beats.value.some((beat) => beat.durationMs <= 0))

  let timer: ReturnType<typeof setInterval> | null = null
  /** 无音频那一句的起算时刻（`now()` 的读数）。 */
  let silentStartedAt = 0
  /**
   * 元素当前装着哪个 URL。
   *
   * 不能拿 `audio.src` 去比：那个属性返回的是**绝对地址**，而清单给的是
   * `/api/...` 的相对路径，两者永远不相等 —— 于是每次刷新清单都重新赋一次
   * `src`，元素跟着重新加载，声音每两秒断一下。记住我们自己赋过的那个值。
   */
  let loadedSrc = ''

  function stopTimer(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  function haltAudio(): void {
    audio.pause()
    // **不把 currentTime 归零**：暂停之后要能接着听。归零是「切句」的事，
    // 由 `play()` 按 `positionMs` 统一对齐，那样位置就只有这一个来源。
  }

  /** 停下来，但不改变 index（暂停 / 打断都走这里）。 */
  function pause(): void {
    playing.value = false
    stopTimer()
    haltAudio()
  }

  /** 回到队列开头（停止）。 */
  function stop(): void {
    pause()
    index.value = 0
    positionMs.value = 0
  }

  /**
   * 装队列。
   *
   * `keepPosition` 为真时停在**同一句的同一个位置**上：合成期间会不停重拉清单
   * （`readyCount` 涨了），URL 从空串变成带哈希的地址。此时若把位置归零，
   * 用户会看到老师在原地反复重念这一句 —— 而「刷新清单」本来不该被听见。
   */
  function load(next: AudioBeat[], opts: { keepPosition?: boolean } = {}): void {
    const anchorId = index.value > 0 || positionMs.value > 0 ? current.value?.beatId : ''
    const keepMs = positionMs.value
    const wasPlaying = playing.value
    pause()
    beats.value = next
    const keep = opts.keepPosition !== false && anchorId
    const found = keep ? next.findIndex((beat) => beat.beatId === anchorId) : -1
    index.value = found >= 0 ? found : 0
    // 同一句但句子变短了（替身音频换成了真音频）时把位置夹回去，别停在句子外
    positionMs.value = found >= 0 ? clamp(keepMs, 0, beatDurationMs(next[found])) : 0
    if (wasPlaying && next.length) void play()
  }

  /** 开始播当前这一句（有声走 audio，没声走计时器）。 */
  async function play(): Promise<void> {
    const beat = current.value
    if (!beat) return
    if (positionMs.value >= beatDurationMs(beat) && beatDurationMs(beat) > 0) {
      positionMs.value = 0
    }
    error.value = ''
    playing.value = true
    if (beat.url) {
      // 清单里的 url 是 `/api/...` 的相对路径：同源（生产）或经 Vite 代理（开发），
      // 直接塞给元素即可 —— 前端不该出现后端主机的拼接逻辑。
      const target = positionMs.value / 1000
      if (loadedSrc !== beat.url) {
        audio.src = beat.url
        loadedSrc = beat.url
        // 换了源就得重新对齐：加载算法会把位置清成 0，这一下不能省
        audio.currentTime = target
      } else if (Math.abs(audio.currentTime - target) > 0.25) {
        // 同一个源上差得超过一个 tick 才 seek：小节拍上反复 seek 会爆音
        audio.currentTime = target
      }
      try {
        await audio.play()
      } catch (err) {
        // 自动播放被浏览器拦下是最常见的一种（用户还没交互过）。
        // 这不是「语音坏了」：把话说清楚，并把播放状态退回去，别让按钮骗人。
        playing.value = false
        error.value = `浏览器拦下了播放（${err instanceof Error ? err.message : '未知原因'}），点一下播放键即可`
        return
      }
    } else {
      // 没音频：从当前位置起算，按 estSec 走
      silentStartedAt = now() - positionMs.value / rate.value
    }
    startTimer()
  }

  async function toggle(): Promise<void> {
    if (playing.value) {
      pause()
      return
    }
    await play()
  }

  function startTimer(): void {
    stopTimer()
    timer = setInterval(tick, TICK_MS)
  }

  function tick(): void {
    const beat = current.value
    if (!beat) {
      pause()
      return
    }
    const duration = beatDurationMs(beat)
    if (beat.url) {
      positionMs.value = Math.max(0, audio.currentTime * 1000)
      if (audio.ended || (duration > 0 && positionMs.value >= duration)) {
        void advance()
      }
      return
    }
    positionMs.value = Math.max(0, (now() - silentStartedAt) * rate.value)
    if (duration <= 0 || positionMs.value >= duration) void advance()
  }

  /** 播完一句：有下一句就接着播，没有就停下（并留在最后一句上）。 */
  async function advance(): Promise<void> {
    if (index.value >= beats.value.length - 1) {
      pause()
      positionMs.value = beatDurationMs(beats.value[index.value])
      options.onEnd?.()
      return
    }
    index.value += 1
    positionMs.value = 0
    if (playing.value) await play()
  }

  async function goTo(nextIndex: number): Promise<void> {
    const bounded = clamp(nextIndex, 0, Math.max(0, beats.value.length - 1))
    const wasPlaying = playing.value
    pause()
    index.value = bounded
    positionMs.value = 0
    if (wasPlaying) await play()
  }

  async function next(): Promise<void> {
    await goTo(index.value + 1)
  }

  async function prev(): Promise<void> {
    // 播过 3 秒以上时「上一句」先回到本句开头 —— 与所有播放器一致
    if (positionMs.value > 3000) {
      positionMs.value = 0
      if (playing.value) await play()
      return
    }
    await goTo(index.value - 1)
  }

  async function seekRatio(ratio: number): Promise<void> {
    const total = totalMs.value
    if (!beats.value.length || total <= 0) return
    const target = clamp(ratio, 0, 1) * total
    let acc = 0
    for (let i = 0; i < beats.value.length; i += 1) {
      const duration = beatDurationMs(beats.value[i])
      if (acc + duration >= target) {
        const wasPlaying = playing.value
        pause()
        index.value = i
        positionMs.value = clamp(target - acc, 0, duration)
        if (wasPlaying) await play()
        return
      }
      acc += duration
    }
  }

  function setRate(value: number): void {
    rate.value = value
    audio.playbackRate = value
  }

  // 页面走人：定时器收掉、声音停住，**`playing` 也归位**。只收定时器的话，
  // 这个 ref 会停在 `true` 上 —— 留下的那个「还在播」的假状态，谁在卸载后再看一眼都会读错。
  onScopeDispose(pause)

  return {
    beats,
    index,
    playing,
    positionMs,
    rate,
    error,
    current,
    totalMs,
    elapsedMs,
    estimated,
    playableCount,
    load,
    play,
    pause,
    toggle,
    stop,
    goTo,
    next,
    prev,
    seekRatio,
    setRate,
  }
}
