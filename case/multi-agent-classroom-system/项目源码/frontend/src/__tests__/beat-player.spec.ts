/**
 * 课堂的声音与「这一句讲完了」（P3-A2 / P3-A5）。
 *
 * 这一份盯的是**收尾那两条路**：音频播完了（`ended`）与服务端说完了
 * （`speak_end`）。两条都报一次的话时间线会多走一格，而那一格是凭空跳过去的、
 * 没有对应的讲解；一条都不报的话课就停在那儿不动。所以「报了没有、报了几次、
 * 什么时候不该报」是这份用例的全部内容。
 *
 * 音频元素与 rAF 都是注入的替身：jsdom 里真元素既不出声也不推进时间。
 */

import { effectScope, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useBeatPlayer, type AudioLike } from '@/composables/useBeatPlayer'
import type { SpeakEnd } from '@/stores/classroom'
import type { SpeakPayload } from '@/types/classroom'

/** 一个可推进的假音频。`onended` 由用例手动打 —— 「播完了」是这里的开关。 */
class FakeAudio implements AudioLike {
  src = ''
  volume = 1
  currentTime = 0
  played = 0
  paused = false

  play(): Promise<void> {
    this.played += 1
    this.paused = false
    return Promise.resolve()
  }

  pause(): void {
    this.paused = true
  }

  onended: (() => void) | null = null
  onerror: (() => void) | null = null

  /** 播到 `seconds` 秒然后自然结束。 */
  finish(seconds: number): void {
    this.currentTime = seconds
    this.onended?.()
  }
}

function turn(patch: Partial<SpeakPayload> = {}): SpeakPayload {
  return {
    turnId: 't1',
    speaker: { code: 't1', name: '沈老师' },
    speakerKind: 'teacher',
    text: '感知机接收多个输入。',
    audioUrl: '/api/courses/c1/audio/p3-b1?v=1',
    beats: ['p3-b1'],
    kind: 'lecture',
    priority: 10,
    pageNo: 3,
    ...patch,
  }
}

const scopes: ReturnType<typeof effectScope>[] = []

function makePlayer(options: { claim?: (turnId: string) => boolean } = {}) {
  const speaking = ref<SpeakPayload | null>(null)
  const speakEnd = ref<SpeakEnd | null>(null)
  const done: string[] = []
  const reported = new Set<string>()
  const audios: FakeAudio[] = []

  const scope = effectScope()
  scopes.push(scope)
  const player = scope.run(() =>
    useBeatPlayer({
      speaking,
      speakEnd,
      claim:
        options.claim ??
        ((turnId: string) => {
          if (reported.has(turnId)) return false
          reported.add(turnId)
          return true
        }),
      onBeatDone: (beatId) => done.push(beatId),
      createAudio: () => {
        const audio = new FakeAudio()
        audios.push(audio)
        return audio
      },
    }),
  ) as ReturnType<typeof useBeatPlayer>

  return { player, speaking, speakEnd, done, audios, scope }
}

/** rAF 的替身：回调攒着，用例手动打一帧（jsdom 的 rAF 时间点不由我们说了算）。 */
let frames: FrameRequestCallback[] = []

beforeEach(() => {
  frames = []
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frames.push(callback)
    return frames.length
  })
  vi.stubGlobal('cancelAnimationFrame', (handle: number) => {
    frames[handle - 1] = () => {}
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  while (scopes.length) scopes.pop()?.stop()
})

function tick(): void {
  const pending = frames
  frames = []
  for (const callback of pending) callback(0)
}

describe('出声', () => {
  it('有音频就播：喂上 src、开始响、位置从 0 起', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn()
    await Promise.resolve()

    expect(ctx.audios).toHaveLength(1)
    expect(ctx.audios[0].src).toBe('/api/courses/c1/audio/p3-b1?v=1')
    expect(ctx.audios[0].played).toBe(1)
    expect(ctx.player.playing.value).toBe(true)
    expect(ctx.player.positionMs.value).toBe(0)
  })

  it('位置按帧跟着音频走：字幕的逐词高亮靠它', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn()
    await Promise.resolve()

    ctx.audios[0].currentTime = 1.25
    tick()
    expect(ctx.player.positionMs.value).toBe(1250)

    ctx.audios[0].currentTime = 2.5
    tick()
    expect(ctx.player.positionMs.value).toBe(2500)
  })

  it('**没有音频只上屏**：不建音频元素、不假装在响', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn({ audioUrl: '', kind: 'answer', beats: [] })
    await Promise.resolve()

    expect(ctx.audios).toHaveLength(0)
    expect(ctx.player.playing.value).toBe(false)
    expect(ctx.player.positionMs.value).toBe(0)
  })

  it('静音只把音量关掉：课照走、时间线照推', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn()
    await Promise.resolve()

    ctx.player.setMuted(true)
    expect(ctx.audios[0].volume).toBe(0)

    ctx.speaking.value = turn({ turnId: 't2', beats: ['p3-b2'] })
    await Promise.resolve()
    expect(ctx.audios[1].volume).toBe(0) // 新的一句也是静的

    ctx.player.setMuted(false)
    expect(ctx.audios[1].volume).toBe(1)
  })
})

describe('「说完了」只有一次', () => {
  it('音频播完就报 beat_done', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn()
    await Promise.resolve()

    ctx.audios[0].finish(4)
    expect(ctx.done).toEqual(['p3-b1'])
    expect(ctx.player.playing.value).toBe(false)
  })

  it('两条路都到了也只报一次：音频先播完，`speak_end` 后到', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn()
    await Promise.resolve()

    ctx.audios[0].finish(4)
    ctx.speakEnd.value = { turnId: 't1', preempted: false, kind: 'lecture', at: 1 }
    await nextTick()

    expect(ctx.done).toEqual(['p3-b1'])
  })

  it('没有音频时**只有** `speak_end` 这一条能收尾', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn({ audioUrl: '' })
    await Promise.resolve()

    expect(ctx.done).toEqual([])
    ctx.speakEnd.value = { turnId: 't1', preempted: false, kind: 'lecture', at: 1 }
    await nextTick()
    expect(ctx.done).toEqual(['p3-b1'])
  })

  it('被打断的那一轮不报：这一格没讲完，重讲时是一轮新的 turnId', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn()
    await Promise.resolve()

    ctx.speakEnd.value = { turnId: 't1', preempted: true, kind: 'lecture', at: 1 }
    await nextTick()
    expect(ctx.done).toEqual([])

    // 回到这一句：新一轮，照样能报
    ctx.speaking.value = turn({ turnId: 't2' })
    await Promise.resolve()
    ctx.audios[1].finish(4)
    expect(ctx.done).toEqual(['p3-b1'])
  })

  it('没有 beat 的发言不推进时间线：答疑说完就完了', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn({ kind: 'answer', beats: [], audioUrl: '' })
    await nextTick()
    ctx.speakEnd.value = { turnId: 't1', preempted: false, kind: 'answer', at: 1 }
    await nextTick()

    expect(ctx.done).toEqual([])
  })

  it('迟到的收尾（不是当前这一轮）只把声停掉，不动时间线', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn({ turnId: 't5' })
    await Promise.resolve()

    ctx.speakEnd.value = { turnId: 't-old', preempted: false, kind: 'lecture', at: 1 }
    await nextTick()
    expect(ctx.done).toEqual([])
    expect(ctx.player.playing.value).toBe(false)
  })

  it('播不出来（地址失效）不当成说完了：等 `speak_end`，它一定会来', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn()
    await Promise.resolve()

    ctx.audios[0].onerror?.()
    expect(ctx.done).toEqual([])
    expect(ctx.player.playing.value).toBe(false)

    ctx.speakEnd.value = { turnId: 't1', preempted: false, kind: 'lecture', at: 1 }
    await nextTick()
    expect(ctx.done).toEqual(['p3-b1'])
  })
})

describe('重发与停声', () => {
  it('同一条 `speak` 重发（重连时会）不从头再播一遍', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn()
    await Promise.resolve()

    ctx.speaking.value = { ...turn() } // 同一个 turnId
    await Promise.resolve()
    expect(ctx.audios).toHaveLength(1)

    ctx.speaking.value = turn({ turnId: 't2', beats: ['p3-b2'] })
    await Promise.resolve()
    expect(ctx.audios).toHaveLength(2)
  })

  it('stop 停声、位置归零，**不报** beat_done（这是「先别讲了」，不是「讲完了」）', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn()
    await Promise.resolve()
    ctx.audios[0].currentTime = 1.5
    tick()

    ctx.player.stop()

    expect(ctx.player.playing.value).toBe(false)
    expect(ctx.player.positionMs.value).toBe(0)
    expect(ctx.audios[0].paused).toBe(true)
    expect(ctx.audios[0].onended).toBeNull()
    expect(ctx.done).toEqual([])
  })

  it('离场（作用域停掉）之后音频不会接着说', async () => {
    const ctx = makePlayer()
    ctx.speaking.value = turn()
    await Promise.resolve()

    ctx.scope.stop()
    expect(ctx.audios[0].paused).toBe(true)
    expect(ctx.audios[0].onended).toBeNull()
  })
})
