/**
 * 语音接口层（P2 §4.1 的前端半边）。
 *
 * 与课程接口那份同一条理由：前端不做业务判断，但**路径、方法、body 形状**
 * 要与后端对齐。语音这块多一条：**URL 里不能出现厂商**（AGENTS §4.1）——
 * 浏览器只跟自己的 Flask 说话，厂商的域名与事件名一律在服务端。
 */

import MockAdapter from 'axios-mock-adapter'
import { beforeEach, describe, expect, it } from 'vitest'

import * as api from '@/api'
import { http } from '@/api/client'

let mock: MockAdapter

beforeEach(() => {
  mock = new MockAdapter(http)
})

function ok(data: unknown): [number, Record<string, unknown>] {
  return [200, { code: 0, message: 'ok', data, requestId: 'r1' }]
}

describe('音色与试听', () => {
  it('音色列表打的是 /voice/voices（不是设置页那份）', async () => {
    let path = ''
    mock.onGet('/voice/voices').reply((config) => {
      path = String(config.url)
      return ok({ items: [], total: 0, current: '', provider: '', enabled: true, usable: false })
    })

    const list = await api.fetchVoices()

    expect(path).toBe('/voice/voices')
    expect(list.usable).toBe(false)
  })

  it('试听把文本与 force 原样发出去', async () => {
    let body: unknown
    let path = ''
    mock.onPost('/voice/voices/vp_teacher_shen/preview').reply((config) => {
      path = String(config.url)
      body = JSON.parse(String(config.data))
      return ok({
        voiceId: 'vp_teacher_shen',
        url: '/api/voice/voices/vp_teacher_shen/preview?v=abc',
        cached: true,
        durationMs: 3200,
        text: '同学们好',
        provider: 'volc_tts',
      })
    })

    const result = await api.previewVoice('vp_teacher_shen', { text: '同学们好' })

    expect(path).toBe('/voice/voices/vp_teacher_shen/preview')
    expect(body).toEqual({ text: '同学们好' })
    // 试听音频的地址是**相对路径**（同源或经 Vite 代理），不是厂商域名
    expect(result.url.startsWith('/api/')).toBe(true)
  })
})

describe('整课预合成与清单', () => {
  it('合成请求的参数只带给了的（空的 force/pageNo 不出现）', async () => {
    let params: Record<string, unknown> = {}
    mock.onPost('/courses/c1/narrate').reply((config) => {
      params = config.params ?? {}
      return ok({
        courseId: 'c1',
        beats: [],
        readyCount: 0,
        beatCount: 0,
        running: true,
        started: true,
      })
    })

    const result = await api.narrateCourse('c1')

    expect(params).toEqual({})
    expect(result.started).toBe(true)
  })

  it('清单是 GET，播放器的输入全部来自它', async () => {
    let path = ''
    mock.onGet('/courses/c1/audio-manifest').reply((config) => {
      path = String(config.url)
      return ok({ courseId: 'c1', beats: [], readyCount: 0, beatCount: 0, running: false })
    })

    await api.fetchAudioManifest('c1')

    expect(path).toBe('/courses/c1/audio-manifest')
  })
})

describe('识别与用量', () => {
  it('识别走 multipart，文件名带着真后缀', async () => {
    let path = ''
    mock.onPost('/voice/asr').reply((config) => {
      path = String(config.url)
      return ok({ text: '学习率为什么要衰减', final: true, durationMs: 1800, segments: [] })
    })

    // 假适配器会把 FormData 序列化成 `{"file":{}}`，文件名在那一步就没了 ——
    // 所以盯的是**装进去的那一刻**：后端按文件名判格式，后缀丢了它只能猜。
    const appended: unknown[][] = []
    const realAppend = FormData.prototype.append
    const spy = vi
      .spyOn(FormData.prototype, 'append')
      .mockImplementation(function (this: FormData, ...args: unknown[]) {
        appended.push(args)
        return realAppend.apply(this, args as never)
      })

    const result = await api.transcribeAudio(new Blob([new Uint8Array([1, 2])]), 'ask.wav')
    spy.mockRestore()

    expect(path).toBe('/voice/asr')
    expect(appended).toHaveLength(1)
    expect(appended[0][0]).toBe('file')
    expect(appended[0][1]).toBeInstanceOf(Blob)
    expect(appended[0][2]).toBe('ask.wav')
    expect(result.text).toBe('学习率为什么要衰减')
  })

  it('用量带筛选参数，空值不发', async () => {
    let params: Record<string, unknown> = {}
    mock.onGet('/voice/usage').reply((config) => {
      params = config.params ?? {}
      return ok({ kinds: [], totalCost: 0, priced: false, refType: 'course', refId: 'c1' })
    })

    await api.fetchVoiceUsage({ refType: 'course', refId: 'c1' })
    expect(params).toEqual({ refType: 'course', refId: 'c1' })

    await api.fetchVoiceUsage()
    expect(params).toEqual({})
  })
})

describe('实时语音的地址', () => {
  it('走 /ws（不是 /api），协议跟着页面走', () => {
    // jsdom 的地址是 http://localhost:3000/
    expect(api.realtimeUrl('t-1')).toBe('ws://localhost:3000/ws/voice/realtime?ticket=t-1')
  })

  it('票据要转义：它是随机串，但不该在拼地址时被当成结构', () => {
    expect(api.realtimeUrl('a b&c=d')).toContain('ticket=a%20b%26c%3Dd')
  })

  it('没有票据就不带参数 —— 缺票那条路要让服务端拒绝，而不是拼出个坏地址', () => {
    expect(api.realtimeUrl('')).toBe('ws://localhost:3000/ws/voice/realtime')
  })

  it('前端这条路上不出现任何厂商域名', () => {
    const url = api.realtimeUrl('t-1')
    expect(url).toContain(window.location.host)
    expect(url).not.toMatch(/volc|bytedance|doubao|openspeech/i)
  })
})
