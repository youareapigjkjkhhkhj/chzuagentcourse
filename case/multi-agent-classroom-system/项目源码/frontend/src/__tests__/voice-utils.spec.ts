/**
 * 语音的几条前端口径（P2-A3 / P2-B2 / P2-G3）。
 *
 * 这一份盯的是「前端不许自己判断」这件事：退到哪条路由**服务端**说了算，
 * 有没有声音由**清单**说了算，字幕高亮的位置由**上游给的时间戳**说了算。
 * 每一条都写了「判断错的时候会怎样」，因为这几条错法的症状都很轻
 * （画面照常，只是慢半拍、或者弹了一个不该弹的错），不写下来就会被改回去。
 */

import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import {
  beatDurationMs,
  captionParts,
  cueIndexAt,
  fallbackHint,
  fallbackOf,
  formatClock,
  formatCost,
  formatUnits,
  isPlayable,
  noVoiceReason,
} from '@/utils/voice'
import type { AudioBeat } from '@/types/api'

function beat(patch: Partial<AudioBeat> = {}): AudioBeat {
  return {
    pageNo: 1,
    beatId: 'p1-b1',
    textHash: 'h1',
    url: '/api/courses/c1/audio/p1-b1?v=abc',
    durationMs: 4000,
    text: '同学们好，我是这门课的老师。',
    estSec: 4,
    status: 'ready',
    subtitles: [
      { text: '同学们好，', startMs: 0, endMs: 1200 },
      { text: '我是这门课的', startMs: 1200, endMs: 3000 },
      { text: '老师。', startMs: 3000, endMs: 4000 },
    ],
    ...patch,
  }
}

describe('降级路径由服务端说了算（P2-B2）', () => {
  it('40302 那封信封是平铺的（data.fallback）', () => {
    const error = new ApiError(40302, '语音功能已关闭', {
      ok: false,
      error: 'voice_disabled',
      fallback: 'text',
    })

    expect(fallbackOf(error)).toBe('text')
  })

  it('其余错误走 details.fallback', () => {
    const error = new ApiError(40201, '上游拒绝了这次请求', {
      details: { fallback: 'browser' },
    })

    expect(fallbackOf(error)).toBe('browser')
  })

  it('服务端没说的就当没说过，宁可退到纯文字', () => {
    // 退到 browser 会在没有 speechSynthesis 的环境里静默失败；
    // 退到 text 一定不会出错 —— 所以读不出来时按 text 说
    expect(fallbackOf(new ApiError(50001, '炸了'))).toBe('')
    expect(fallbackHint('')).toBe(fallbackHint('text'))
    expect(fallbackOf(new Error('不是 ApiError'))).toBe('')
  })

  it('三种降级各有各的说法，条数不多不少', () => {
    expect(fallbackHint('text')).toContain('文字问答')
    expect(fallbackHint('browser')).toContain('浏览器')
    expect(fallbackHint('none')).toContain('设置页')
  })
})

describe('「为什么没有声音」的几种说法来自清单里的代码', () => {
  it('开关关掉与没配音色，说法不一样', () => {
    expect(noVoiceReason('voice_disabled')).toContain('VOICE_ENABLED')
    expect(noVoiceReason('voice_not_configured')).toContain('设置页')
  })

  it('不认识的代码就不编一句话', () => {
    expect(noVoiceReason('something_new')).toBe('')
  })
})

describe('一句能不能播只看 url', () => {
  it('空 url 就是没声音', () => {
    expect(isPlayable(beat())).toBe(true)
    expect(isPlayable(beat({ url: '' }))).toBe(false)
  })

  it('时长优先用音频的，没有才按 estSec 估', () => {
    expect(beatDurationMs(beat())).toBe(4000)
    expect(beatDurationMs(beat({ durationMs: 0, estSec: 6 }))).toBe(6000)
  })
})

describe('字幕高亮（P2-A3）', () => {
  it('命中最后一条 startMs <= 当前毫秒的片段', () => {
    const sample = beat()
    expect(cueIndexAt(sample, 0)).toBe(0)
    expect(cueIndexAt(sample, 1199)).toBe(0)
    expect(cueIndexAt(sample, 1200)).toBe(1)
    expect(cueIndexAt(sample, 9999)).toBe(2)
  })

  it('没有时间戳时返回 -1，由调用方退成整句（不假装精确）', () => {
    expect(cueIndexAt(beat({ subtitles: [] }), 1000)).toBe(-1)
    expect(cueIndexAt(null, 1000)).toBe(-1)
  })

  it('片段拼得回整句才切分：高亮的是时间戳指的那一段', () => {
    expect(captionParts(beat(), 1500)).toEqual({
      before: '同学们好，',
      active: '我是这门课的',
      after: '老师。',
    })
  })

  it('片段拼不回整句就不切 —— 少一个动画，好过多一句对不上的假字幕', () => {
    // 上游只给了「词」而整句里有空格/标点：拼起来对不上，这时不能随便切
    const broken = beat({
      text: '同学们好，我是这门课的老师。',
      subtitles: [{ text: '同学们好', startMs: 0, endMs: 1200 }],
    })
    expect(captionParts(broken, 500)).toBeNull()
    expect(captionParts(null, 500)).toBeNull()
  })
})

describe('给人看的几种写法', () => {
  it('时间一律「分:秒」', () => {
    expect(formatClock(0)).toBe('0:00')
    expect(formatClock(65_400)).toBe('1:05')
    expect(formatClock(Number.NaN)).toBe('0:00')
  })

  it('用量单位由服务端给，前端只翻译', () => {
    expect(formatUnits('chars', 1200)).toBe('1200 字符')
    expect(formatUnits('seconds', 30)).toBe('30 秒')
    expect(formatUnits('pages', 3)).toBe('3 pages')
  })

  it('金额四位小数：一次课堂多半只有几分钱', () => {
    expect(formatCost(0.0123)).toBe('¥0.0123')
    expect(formatCost(0)).toBe('¥0.0000')
  })
})
