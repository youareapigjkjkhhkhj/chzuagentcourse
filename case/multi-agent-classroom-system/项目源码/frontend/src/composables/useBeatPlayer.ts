/**
 * 课堂的声音与「这一句讲完了」（P3-A2 / P3-A5）。
 *
 * 一条发言（`speak` 事件）到了之后要做三件事：出声、上屏、**在说完之后让时间线
 * 往前走一格**。前两件是显示，第三件是这张课能不能自己上下去的关键 ——
 * 服务端不在讲稿里自己推进（它不知道这句话在学生的机器上播到哪了），
 * 它等客户端报一条 `beat_done`（见 `runtime._on_beat_done`）。
 *
 * **什么时候算「说完了」有两条路，谁先到算谁**：
 *
 * - 音频播完了（`ended`）—— 有音频时这是最准的那条；
 * - 服务端发来 `speak_end` —— 没有音频时**只有**这一条（讲稿要预合成过才有
 *   音频，教师答疑是当场合成的，配不上 TTS 就没有声音，`audioUrl` 是空串）。
 *
 * 两条都报一次的话时间线会多走一格，而那一格是凭空跳过去的、没有对应的讲解；
 * 所以按 `turnId` 去重（`claimBeatReport`），一个 turn 只报一次。
 *
 * **被打断的（`preempted`）不报**：老师那句被学生的问题截断了，这一格没讲完，
 * 时间线不该往前走 —— 学生问答结束之后回到这里，会**重新**讲这一句
 * （`_on_play` → `_speak_current_beat`），那是一轮新的 `turnId`，到那时再报。
 *
 * **播不出来不算失败**：浏览器的自动播放策略可能拦下 `play()`（用户在那一拍
 * 没有交互），这时音频不会播也不会触发 `ended`，于是这一格等 `speak_end` 收尾 ——
 * 服务端按 `_speak_ms` 计时（有音频用真时长、没有就按字数估），到点照样发。
 * 少一段声音，课上得下去。
 */

import { onScopeDispose, ref, watch, type Ref } from 'vue'

import type { SpeakEnd } from '@/stores/classroom'
import type { SpeakPayload } from '@/types/classroom'

/**
 * 音频元素。`HTMLAudioElement` 结构上满足它，测试塞一个假的。
 *
 * 只声明这一层真的会碰的那几个成员：`play` / `pause` / `src` / `onended` /
 * `onerror` 加一个音量。多声明一个，假替身就得多实现一个。
 */
export interface AudioLike {
  src: string
  volume: number
  /** 播到第几毫秒了。字幕的逐词高亮靠它（P2-A3 那条口径在课堂里也要有）。 */
  currentTime: number
  play(): Promise<void> | void
  pause(): void
  onended: (() => void) | null
  onerror: (() => void) | null
}

export interface BeatPlayerOptions {
  /** 当前这一条发言（store 的 `speaking`）。 */
  speaking: Ref<SpeakPayload | null>
  /** 上一条发言的收尾（store 的 `speakEnd`）。 */
  speakEnd: Ref<SpeakEnd | null>
  /**
   * 这一轮要不要报 `beat_done`（store 的 `claimBeatReport`）。
   * **去重归它管** —— 报两次会让时间线多走一格，而这里管不到另一条路。
   */
  claim: (turnId: string) => boolean
  /** 报一次 `beat_done`。 */
  onBeatDone: (beatId: string) => void
  createAudio?: () => AudioLike
  /** 开始播一条（页面用它做「老师正在说」的动效）。 */
  onTurn?: (turn: SpeakPayload) => void
}

export interface BeatPlayer {
  /** 这条发言的音频在响。**没有音频的发言永远是 false**（不代表它没说）。 */
  playing: Ref<boolean>
  /**
   * 这一段播到第几毫秒了。
   *
   * 字幕的逐词高亮按它算（与 P2 的讲稿播放器同一条口径）。**没有音频时一直是 0**
   * —— 那时候高亮的位置没有任何依据，退成整句显示（`captionParts` 拿 0 就返回 null）。
   */
  positionMs: Ref<number>
  /** 静音。讲课的声音与时间线是两件事：静音了照样计时、照样推进。 */
  muted: Ref<boolean>
  setMuted: (value: boolean) => void
  /** 立即停声（页面上按下暂停、或离开时用）。**不报 `beat_done`**。 */
  stop: () => void
}

export function useBeatPlayer(options: BeatPlayerOptions): BeatPlayer {
  const createAudio = options.createAudio ?? (() => new Audio() as unknown as AudioLike)

  const playing = ref(false)
  const positionMs = ref(0)
  const muted = ref(false)

  let audio: AudioLike | null = null
  /** 当前这一轮。`speaking` 会在 `speak_end` 时被清空，所以这里自己留一份。 */
  let turn: SpeakPayload | null = null
  /** 已经为哪一轮起过声 —— 同一条 `speak` 重发（重连时会）不重头播。 */
  let playedTurnId = ''
  let frame = 0

  /**
   * 用 rAF 自己读 `currentTime`，不听 `timeupdate`。
   *
   * `timeupdate` 一秒只来 4 次左右（约 250ms 一拍），而字幕的片段是 300ms 级的 ——
   * 拿它驱动高亮，得到的是一块一跳一跳的字幕。自己按帧读，60fps 下就是连续的。
   * 播完就停，不留着一个转圈的 rAF。
   */
  function tick(): void {
    if (!audio) {
      frame = 0
      return
    }
    positionMs.value = Math.max(0, Math.round((audio.currentTime || 0) * 1000))
    frame = requestAnimationFrame(tick)
  }

  /**
   * 把声收掉：停元素、取消回调、收掉 rAF。
   *
   * **位置留着**（`positionMs` 不动）—— 一句刚说完时字幕该停在最后一个词上，
   * 归零会让它跳回第一个词，看起来像这句话又说了一遍。
   */
  function settle(): void {
    const current = audio
    audio = null
    playing.value = false
    if (frame) {
      cancelAnimationFrame(frame)
      frame = 0
    }
    if (!current) return
    current.onended = null
    current.onerror = null
    try {
      current.pause()
    } catch {
      // 已经自然结束的音频 pause 一下没什么可抛的，抛了也不影响后面
    }
  }

  /** 立刻停声（页面按了暂停、或者离开课堂）。位置归零：这一句不讲了。 */
  function stop(): void {
    settle()
    positionMs.value = 0
  }

  /**
   * 这一轮说完了（音频播完 / `speak_end` 先到）。**先收声再报**，去重之后报一次。
   *
   * 收声这一步不能省：音频自然播完之后元素不会自己把 `playing` 置回去，
   * 那个 rAF 也会一直转下去 —— 图标会一直显示「暂停」，而且每帧读一次
   * 已经结束的音频，直到下一句开口。
   */
  function complete(finished: SpeakPayload | null): void {
    if (!finished) return
    settle()
    if (finished.beats.length) {
      if (!options.claim(finished.turnId)) return
      options.onBeatDone(finished.beats[0])
      return
    }
    // 没有 beat 的不是讲稿（答疑、插话、讨论）：它们说完就完了，时间线不动。
    //
    // **测验反馈那一句是例外**：它不是插在讲稿之间的一句闲话，而是**这道题
    // 过了**这件事本身（`runtime._say_feedback`）。它说完的那一刻正是「接着往下
    // 讲」的那一刻，不报这一下，课堂就停在答完题的地方不动了 —— 与「跳过这道题」
    // 按的那个 `beat_done` 是同一条（空 `beatId`：位置由服务端的会话行说了算）。
    if (finished.kind !== 'feedback') return
    if (!options.claim(finished.turnId)) return
    options.onBeatDone('')
  }

  function start(next: SpeakPayload): void {
    stop()
    turn = next
    options.onTurn?.(next)
    // 空 `audioUrl` 是常态不是异常：这条按纯文字走，等 `speak_end` 收尾
    if (!next.audioUrl) return
    const element = createAudio()
    element.src = next.audioUrl
    element.volume = muted.value ? 0 : 1
    element.onended = () => complete(next)
    element.onerror = () => {
      // 播不出来（地址失效、格式不认）：**不当成说完了**。等 `speak_end` ——
      // 它一定会来，服务端那边是按时间计的，与这边播没播出声无关。
      playing.value = false
    }
    audio = element
    playing.value = true
    positionMs.value = 0
    frame = requestAnimationFrame(tick)
    try {
      void Promise.resolve(element.play()).catch(() => {
        // 自动播放被拦：同上，交给 `speak_end`。下一拍用户点一下页面就好了。
        playing.value = false
      })
    } catch {
      playing.value = false
    }
  }

  watch(
    options.speaking,
    (next) => {
      if (!next || next.turnId === playedTurnId) return
      playedTurnId = next.turnId
      start(next)
    },
    { immediate: true },
  )

  watch(options.speakEnd, (ended) => {
    if (!ended) return
    const current = turn
    // 迟到的收尾（不是当前这一轮）：只管把声停掉，不推进时间线
    if (!current || current.turnId !== ended.turnId) {
      stop()
      return
    }
    turn = null
    // 说完了才报（`complete` 里一并收声）；被打断的这一格没讲完，不报
    if (ended.preempted) stop()
    else complete(current)
  })

  function setMuted(value: boolean): void {
    muted.value = value
    if (audio) audio.volume = value ? 0 : 1
  }

  // 离开课堂时把声停掉、把 rAF 收掉：留着的话音频会在别的页面上继续说，
  // 而那个 rAF 会一直跑到标签页关掉为止
  onScopeDispose(stop)

  return { playing, positionMs, muted, setMuted, stop }
}
