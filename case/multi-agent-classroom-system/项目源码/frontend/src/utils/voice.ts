/**
 * 语音的几条前端口径（P2-B2 / P2-G3）。
 *
 * 一条纪律写在最前面：**退到哪条路由服务端说了算**。
 * 语音失败时前端不许自己判断「这个错是不是没配 Key、要不要改成打字」——
 * 判断逻辑有两份，就会在不同的时间点过期：后端加了一种失败原因，前端的
 * 判断还是旧的，于是它按旧逻辑弹了一个红色错误框。一节课中间弹一次，
 * 这节课就断了。所以这里只做一件事：把服务端给的 `fallback` 读出来。
 */

import { ApiError } from '@/api/client'
import type { AudioBeat, VoiceFallback } from '@/types/api'

/**
 * 从错误里读出降级路径。
 *
 * 两种嵌套都要认：40302 的信封是**平铺**的（`data.fallback`），其余错误走
 * `data.details.fallback`（见后端 `policy.with_fallback`）。读不到返回空串 ——
 * 那表示服务端没说，此时按「纯文字」处理比按「浏览器合成」处理安全：
 * 前者一定不会出错，后者会在一个没有 `speechSynthesis` 的环境里静默失败。
 */
export function fallbackOf(error: unknown): VoiceFallback | '' {
  if (!(error instanceof ApiError)) return ''
  const data = error.data
  if (typeof data !== 'object' || data === null) return ''
  const flat = (data as { fallback?: unknown }).fallback
  if (typeof flat === 'string' && flat) return flat as VoiceFallback
  const details = (data as { details?: unknown }).details
  if (typeof details === 'object' && details !== null) {
    const nested = (details as { fallback?: unknown }).fallback
    if (typeof nested === 'string' && nested) return nested as VoiceFallback
  }
  return ''
}

/** 降级提示条的文案。键是服务端的枚举值，不是我们自己发明的状态。 */
export const FALLBACK_HINTS: Record<VoiceFallback, string> = {
  text: '实时语音不可用，已切换为文字问答：打字提问照常，讲稿与字幕都还在。',
  browser: '服务端暂时合成不了语音，已改用浏览器本地朗读（音色与语速会不一样）。',
  none: '语音暂时用不了，也没有可退的路 —— 请检查设置页的语音服务。',
}

/** 读不出来的错误按 `text` 处理，理由见 `fallbackOf` 的注释。 */
export function fallbackHint(fallback: VoiceFallback | ''): string {
  return FALLBACK_HINTS[(fallback || 'text') as VoiceFallback]
}

/**
 * 清单里「为什么没有声音」的几种说法。
 *
 * 这些是 `manifest()` 给出的**代码**（`voice_disabled` / `voice_not_configured` /
 * `provider_not_configured`），服务端在清单里只给代码不给句子 —— 这句话要
 * 说的是「你现在能做什么」，而那是界面的事。
 */
const NO_VOICE_REASONS: Record<string, string> = {
  voice_disabled: '语音功能已关闭（VOICE_ENABLED=false）—— 这是一节纯文字的课堂。',
  voice_not_configured:
    '还没有可用的音色：去设置页把音色配上厂商声音 ID，课堂才有声音。',
  provider_not_configured:
    '语音服务商还没配好（缺凭据）—— 配好之后在设置页点「试听」就能先听到。',
}

export function noVoiceReason(reason: string): string {
  return NO_VOICE_REASONS[reason] ?? ''
}

/** 清单里的一句能不能播。空 `url` 就是没有声音，别的地方一律问这一个函数。 */
export function isPlayable(beat: AudioBeat): boolean {
  return Boolean(beat.url)
}

/**
 * 当前该高亮第几个字。
 *
 * `subtitles` 是**字级时间戳**（P2-A3）：命中最后一条 `startMs <= 当前毫秒` 的。
 * 没有时间戳（上游没给）时返回 -1，由调用方退回「整句高亮」—— 误差 300ms 的
 * 口径就是这么来的：整句切换不可能更精确，所以不假装精确。
 */
export function cueIndexAt(beat: AudioBeat | null, positionMs: number): number {
  if (!beat || !beat.subtitles.length) return -1
  let index = -1
  for (let i = 0; i < beat.subtitles.length; i += 1) {
    if (beat.subtitles[i].startMs <= positionMs) index = i
    else break
  }
  return index
}

/** 字幕的三段切分：高亮中间那段，前后照常显示。 */
export interface CaptionParts {
  before: string
  active: string
  after: string
}

/**
 * 把一句讲稿按**当前进度**切成三段，给字幕区做逐词高亮（P2-A3）。
 *
 * 高亮的位置来自字级时间戳（`cueIndexAt`），但切分只能在**整句文本**上做：
 * 前端不能把几段时间戳拼起来当句子显示 —— 上游给的片段是「词」，
 * 拼接处该不该有空格是上游的排版细节，前端拼一遍就会出现「老 师 同 学 们」。
 *
 * 所以：片段能**首尾相接拼回整句**（这是上游的正常形态）才切分；
 * 拼不回去就返回 null，由调用方退到「整句照常显示、不高亮」——
 * 少一个动画，好过多一句和音频对不上的假字幕。
 */
export function captionParts(beat: AudioBeat | null, positionMs: number): CaptionParts | null {
  if (!beat) return null
  const index = cueIndexAt(beat, positionMs)
  if (index < 0) return null
  const joined = beat.subtitles.map((cue) => cue.text).join('')
  if (joined !== beat.text) return null
  const before = beat.subtitles
    .slice(0, index)
    .map((cue) => cue.text)
    .join('')
  const active = beat.subtitles[index].text
  return { before, active, after: joined.slice(before.length + active.length) }
}

/** 一句的时长：有音频用音频的，没有就按 `estSec` 估（P2-A3 的降级口径）。 */
export function beatDurationMs(beat: AudioBeat): number {
  if (beat.durationMs > 0) return beat.durationMs
  return Math.max(0, Math.round(beat.estSec * 1000))
}

/** 毫秒 → 「0:05」「1:05」。播放器上只出现这一种时间写法。 */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor((Number.isFinite(ms) ? ms : 0) / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

/** 用量单位 → 人话。单位名由服务端给（chars / seconds），前端只负责翻译。 */
export function formatUnits(unitName: string, units: number): string {
  if (unitName === 'chars') return `${units} 字符`
  if (unitName === 'seconds') return `${units} 秒`
  return `${units} ${unitName}`
}

/** 估算金额 → 「¥0.0123」。四位小数：一次课堂多半只有几分钱。 */
export function formatCost(cost: number): string {
  return `¥${(Number.isFinite(cost) ? cost : 0).toFixed(4)}`
}
