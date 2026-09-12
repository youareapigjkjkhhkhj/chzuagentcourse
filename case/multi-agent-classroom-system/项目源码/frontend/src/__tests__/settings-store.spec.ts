/**
 * 设置 store 的行为约定。
 *
 * 最重要的一条：**读操作吞异常、写操作抛异常**。
 * 读失败时把原因记进 lastError 让页面照常渲染；写失败必须抛出去，
 * 否则用户会以为保存成功了。
 */

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { describeError, useSettingsStore } from '@/stores/settings'
import type { ProviderCard } from '@/types/api'

vi.mock('@/api', () => ({
  fetchProviders: vi.fn(),
  fetchVoice: vi.fn(),
  fetchGeneration: vi.fn(),
  fetchRoles: vi.fn(),
  fetchCapabilities: vi.fn(),
  fetchHealth: vi.fn(),
  saveProvider: vi.fn(),
  probeProvider: vi.fn(),
  enableProvider: vi.fn(),
  saveVoice: vi.fn(),
  saveGeneration: vi.fn(),
}))

import * as api from '@/api'

function card(overrides: Partial<ProviderCard> = {}): ProviderCard {
  return {
    id: 'deepseek',
    name: 'DeepSeek',
    kind: 'llm',
    baseUrl: '',
    defaultModel: 'deepseek-chat',
    enabled: false,
    configured: true,
    available: true,
    implemented: true,
    maskedKey: 'sk-****4321',
    missing: [],
    latencyMs: null,
    extra: {},
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.fetchProviders).mockResolvedValue({ items: [card()], total: 1 })
  vi.mocked(api.fetchVoice).mockResolvedValue({
    voices: [],
    teacherVoiceId: 'vp_teacher_shen',
    speed: 1,
    intonation: 'natural',
    asrEnabled: true,
    asrBrowserLocal: true,
  })
  vi.mocked(api.fetchGeneration).mockResolvedValue({
    pageCount: 12,
    classmateCount: 3,
    intensity: 'medium',
    scriptDetail: 'detailed',
    autoIllustration: true,
    quizPerChapter: true,
    whiteboard: true,
  })
  vi.mocked(api.fetchRoles).mockResolvedValue({ items: [], total: 0 })
  vi.mocked(api.fetchCapabilities).mockResolvedValue({
    env: 'development',
    version: '0.1.0',
    capabilities: {
      llm: { available: true, offline: false, provider: 'deepseek', reason: '' },
      tts: { available: false, offline: false, provider: 'volc_tts', reason: '还没接通' },
      asr: { available: false, offline: true, provider: 'mock', reason: '' },
      realtime: { available: false, offline: true, provider: 'mock', reason: '' },
    },
    providers: {},
    generation: {
      minPageCount: 8,
      maxPageCount: 20,
      minClassmateCount: 0,
      maxClassmateCount: 5,
      minSpeed: 0.5,
      maxSpeed: 2,
      intonations: ['flat', 'natural', 'expressive'],
      intensities: ['low', 'medium', 'high'],
      scriptDetails: ['concise', 'normal', 'detailed'],
    },
  })
  vi.mocked(api.fetchHealth).mockResolvedValue({
    status: 'ok',
    version: '0.1.0',
    db: 'ok',
    providers: { llm: 'ready', tts: 'unconfigured', asr: 'unconfigured', realtime: 'unconfigured' },
    llm: { provider: 'deepseek', model: 'deepseek-chat' },
    issues: [],
  })
})

describe('loadAll', () => {
  it('把六份数据装进 store', async () => {
    const store = useSettingsStore()

    await store.loadAll()

    expect(store.providers).toHaveLength(1)
    expect(store.voice?.teacherVoiceId).toBe('vp_teacher_shen')
    expect(store.generation?.pageCount).toBe(12)
    expect(store.health?.providers.tts).toBe('unconfigured')
    expect(store.lastError).toBe('')
  })

  it('单个接口挂掉不连累其余的，并把原因记下来', async () => {
    vi.mocked(api.fetchHealth).mockRejectedValue(new ApiError(-1, '连接不上后端服务'))
    const store = useSettingsStore()

    await store.loadAll()

    expect(store.providers).toHaveLength(1) // 其他接口照常
    expect(store.lastError).toContain('连接不上后端服务')
    expect(store.loading).toBe(false)
  })

  it('能力清单同时带出滑杆边界（与后端校验同源）', async () => {
    const store = useSettingsStore()

    await store.loadAll()

    expect(store.limits?.maxPageCount).toBe(20)
    expect(store.limits?.minSpeed).toBe(0.5)
  })
})

describe('派生状态', () => {
  it('模型服务列表只含文本模型', async () => {
    vi.mocked(api.fetchProviders).mockResolvedValue({
      items: [
        card(),
        card({ id: 'volc_asr', name: '火山语音识别', kind: 'asr', configured: false }),
      ],
      total: 2,
    })
    const store = useSettingsStore()

    await store.loadProviders()

    expect(store.llmProviders.map((item) => item.id)).toEqual(['deepseek'])
  })
})

describe('写操作', () => {
  it('保存成功后重新拉列表（新 Key 立刻生效）', async () => {
    const store = useSettingsStore()
    vi.mocked(api.saveProvider).mockResolvedValue(card())

    await store.saveProvider('deepseek', { apiKey: 'sk-new' })

    expect(api.saveProvider).toHaveBeenCalledWith('deepseek', { apiKey: 'sk-new' })
    expect(api.fetchProviders).toHaveBeenCalled()
  })

  it('保存失败必须抛出去 —— 页面要能提示用户', async () => {
    const store = useSettingsStore()
    vi.mocked(api.saveProvider).mockRejectedValue(new ApiError(40001, 'API Key 过长'))

    await expect(store.saveProvider('deepseek', { apiKey: 'x'.repeat(10) })).rejects.toThrow(
      'API Key 过长',
    )
  })

  it('探活后刷新卡片上的延迟', async () => {
    const store = useSettingsStore()
    vi.mocked(api.probeProvider).mockResolvedValue({
      ok: true,
      latencyMs: 320,
      model: 'deepseek-chat',
      provider: 'deepseek',
      error: '',
      errorCode: '',
    })

    const result = await store.probe('deepseek')

    expect(result.ok).toBe(true)
    expect(api.fetchProviders).toHaveBeenCalled()
  })
})

describe('describeError', () => {
  it('业务异常原样用后端文案', () => {
    expect(describeError(new ApiError(40201, '未配置 API Key'))).toBe('未配置 API Key')
  })

  it('非 Error 也有话说，不留空白', () => {
    expect(describeError('boom')).toBe('未知错误')
  })
})
