/**
 * 讲稿播放器（P2-A3 / P2-A10 / F2-5）。
 *
 * 这个播放器有两件事同时在做：**播音频**与**报位置**。位置只有它这一个来源
 * （定时读元素 / 自己计时，不挂 timeupdate），因为两套位置来源在切句、
 * 拖动、打断这三种时刻必然对不上，而症状是「字幕慢半拍」这种说不清的错。
 *
 * 所以这里断言的是位置与切句：换源、对齐、接着播、按 estSec 走、跳转。
 * 音频元素与时钟都是注入的替身 —— jsdom 里真元素既不出声也不推进时间。
 */

import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useNarrationPlayer, type AudioLike } from '@/composables/useNarrationPlayer'
import type { AudioBeat } from '@/types/api'

/** 一个可推进的假音频元素：`play()` 不发声，但能记住它被喂了什么。 */
class FakeAudio implements AudioLike {
  src = ''
  currentTime = 0
  playbackRate = 1
  paused = true
  ended = false
  /** 被换过几次源 —— 「刷新清单不该重新加载」这条就靠它证 */
  srcChanges: string[] = []

  play(): Promise<void> {
    this.paused = false
    return Promise.resolve()
  }

  pause(): void {
    this.paused = true
  }
}

/** 假的音频元素，但**记录每次赋 src**（普通类的 setter 拦不到属性赋值，这里用 defineProperty）。 */
function makeAudio(): AudioLike {
  const audio = new FakeAudio()
  let current = ''
  Object.defineProperty(audio, 'src', {
    get: () => current,
    set: (value: string) => {
      if (value !== current) audio.srcChanges.push(value)
      current = value
    },
  })
  return audio
}

function beat(id: string, url: string, durationMs: number, pageNo = 1): AudioBeat {
  return {
    pageNo,
    beatId: id,
    textHash: `h-${id}`,
    url,
    durationMs,
    text: `${id} 的讲稿`,
    estSec: durationMs / 1000,
    status: 'ready',
    subtitles: [],
  }
}

let clock = 0
const now = () => clock

let audio: AudioLike

/** 造出来的作用域都记一笔：用例结束后统一停掉，免得定时器漏到下一个用例里。 */
const scopes: ReturnType<typeof effectScope>[] = []

/**
 * 造一个播放器。
 *
 * 包在 `effectScope` 里：这个 composable 在组件里用，组件卸载时作用域会被
 * 停掉（`onScopeDispose` 收定时器）。测试里不给它一个作用域，那条清理路径
 * 就永远跑不到 —— 而「离开课堂还留着一个每 60ms 转一圈的定时器」是真问题。
 */
function makePlayer(options: Parameters<typeof useNarrationPlayer>[0] = {}) {
  const scope = effectScope()
  scopes.push(scope)
  return scope.run(() =>
    useNarrationPlayer({ createAudio: () => audio, now, ...options }),
  ) as ReturnType<typeof useNarrationPlayer>
}

function setup() {
  clock = 0
  audio = makeAudio()
  return { player: makePlayer(), audio: audio as FakeAudio, scope: scopes[scopes.length - 1] }
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  // 每个用例自己建的作用域在这里收掉：不这么做，上一个用例的定时器会漏到
  // 下一个用例里，「离开页面就停」那条断言数的就不是自己的定时器了
  for (const scope of scopes.splice(0)) scope.stop()
  vi.useRealTimers()
})

describe('队列与切句', () => {
  it('播完一句自动下一句，跨页也照走', async () => {
    const { player, audio: element } = setup()
    player.load([beat('b1', '/a.mp3', 4000), beat('b2', '/b.mp3', 3000, 2)])

    await player.play()
    expect(element.src).toBe('/a.mp3')
    expect(player.current.value?.beatId).toBe('b1')

    // 音频读到 4 秒：这一句完了
    element.currentTime = 4
    vi.advanceTimersByTime(60)
    await Promise.resolve()

    expect(player.index.value).toBe(1)
    expect(element.src).toBe('/b.mp3')
  })

  it('换成同一个 URL 时不重新加载元素（清单每两秒刷新一次，不能每次都断一下）', async () => {
    const { player, audio: element } = setup()
    const beats = [beat('b1', '/a.mp3', 4000)]

    player.load(beats)
    await player.play()
    expect(element.srcChanges).toEqual(['/a.mp3'])

    // 合成期间清单会不停重拉：同一个 beat、同一个 URL，只是对象换了个新的
    player.load([beat('b1', '/a.mp3', 4000)])
    await player.play()

    expect(element.srcChanges).toEqual(['/a.mp3'])
  })

  it('暂停后接着播，位置不回到句首', async () => {
    const { player, audio: element } = setup()
    player.load([beat('b1', '/a.mp3', 8000)])

    await player.play()
    element.currentTime = 3
    vi.advanceTimersByTime(60)
    expect(player.positionMs.value).toBe(3000)

    player.pause()
    await player.play()

    // 位置还在 3 秒上，元素也没被 rewind
    expect(player.positionMs.value).toBe(3000)
    expect(element.currentTime).toBe(3)
  })

  it('没有音频的句子按 estSec 走节奏，课堂不会卡在第一句', async () => {
    const { player } = setup()
    player.load([
      beat('b1', '', 0),
      beat('b2', '/b.mp3', 2000, 2),
    ])
    // 没音频那几句按 estSec 估：0 时长的句子立刻跳过去
    expect(player.estimated.value).toBe(true)

    await player.play()
    vi.advanceTimersByTime(60)

    expect(player.index.value).toBe(1)
  })

  it('整课总时长 = 各句之和，缺音频的那句按 estSec 补', () => {
    const { player } = setup()
    player.load([beat('b1', '/a.mp3', 4000), beat('b2', '', 0)])
    // beat() 造的 estSec = durationMs/1000，所以 0 时长的这一句估 0 秒
    expect(player.totalMs.value).toBe(4000)
  })

  it('播到最后一句就停下，并且停在最后一句上', async () => {
    const onEnd = vi.fn()
    clock = 0
    audio = makeAudio()
    const player = makePlayer({ onEnd })
    player.load([beat('b1', '/a.mp3', 2000)])

    await player.play()
    ;(audio as FakeAudio).currentTime = 2
    vi.advanceTimersByTime(60)
    await Promise.resolve()

    expect(player.playing.value).toBe(false)
    expect(player.index.value).toBe(0)
    expect(player.positionMs.value).toBe(2000)
    expect(onEnd).toHaveBeenCalled()
  })
})

describe('装队列（清单刷新时）', () => {
  it('默认停在同一句的同一个位置：合成完重拉清单不该被听见', async () => {
    const { player, audio: element } = setup()
    player.load([beat('b1', '/a.mp3', 8000), beat('b2', '/b.mp3', 8000, 2)])
    await player.play()
    element.currentTime = 5
    vi.advanceTimersByTime(60)

    // 这一句的音频从「没有」变成「有了」：URL 变了，位置不该跟着归零
    player.load([
      beat('b1', '/a.mp3?v=2', 8000),
      beat('b2', '/b.mp3', 8000, 2),
    ])

    expect(player.index.value).toBe(0)
    expect(player.positionMs.value).toBe(5000)
  })

  it('这一句没了（讲稿被改）就回到开头，不停在一句已经不存在的话上', () => {
    const { player } = setup()
    player.load([beat('b1', '/a.mp3', 8000)])
    player.load([beat('b9', '/c.mp3', 8000)])

    expect(player.current.value?.beatId).toBe('b9')
    expect(player.positionMs.value).toBe(0)
  })
})

describe('跳转与倍速', () => {
  it('按整课比例拖动：落到对应的一句上，句内位置也对', async () => {
    const { player, audio: element } = setup()
    player.load([beat('b1', '/a.mp3', 4000), beat('b2', '/b.mp3', 4000, 2)])
    expect(player.totalMs.value).toBe(8000)

    await player.seekRatio(0.75)

    expect(player.index.value).toBe(1)
    expect(player.positionMs.value).toBe(2000)
    // 暂停时拖进度条只挪位置、不加载音频（按播放键才去取那一段）
    expect(element.src).toBe('')

    await player.play()
    expect(element.src).toBe('/b.mp3')
    expect(element.currentTime).toBe(2)
  })

  it('倍速直接给到元素（P2-A10 的「不变调」是上游的事）', () => {
    const { player, audio: element } = setup()
    player.setRate(1.5)

    expect(player.rate.value).toBe(1.5)
    expect(element.playbackRate).toBe(1.5)
  })

  it('「上一句」在播过 3 秒后先回到本句开头（与所有播放器一致）', async () => {
    const { player, audio: element } = setup()
    player.load([beat('b1', '/a.mp3', 8000), beat('b2', '/b.mp3', 8000, 2)])
    await player.play()
    element.currentTime = 5
    vi.advanceTimersByTime(60)

    await player.prev()
    expect(player.index.value).toBe(0)
    expect(player.positionMs.value).toBe(0)

    element.currentTime = 1
    vi.advanceTimersByTime(60)
    await player.prev()
    // 只播了一秒：这一次才是真的「上一句」（已经是第一句，停住）
    expect(player.index.value).toBe(0)
  })
})

describe('拿不到音频元素时也不装', () => {
  it('浏览器拦下自动播放时说清是浏览器拦的，并把播放状态退回去', async () => {
    clock = 0
    audio = makeAudio()
    audio.play = vi.fn(() => Promise.reject(new Error('NotAllowedError')))
    const player = makePlayer()
    player.load([beat('b1', '/a.mp3', 4000)])

    await player.play()

    expect(player.playing.value).toBe(false)
    expect(player.error.value).toContain('浏览器')
  })

  it('空队列按下播放什么都不做', async () => {
    const { player } = setup()
    await player.play()
    expect(player.playing.value).toBe(false)
  })

  it('离开页面（作用域停掉）后定时器就不转了', async () => {
    const { player, scope } = setup()
    player.load([beat('b1', '/a.mp3', 8000)])
    await player.play()
    expect(vi.getTimerCount()).toBeGreaterThan(0)

    scope.stop()

    expect(vi.getTimerCount()).toBe(0)
    expect(player.playing.value).toBe(false)
  })
})
