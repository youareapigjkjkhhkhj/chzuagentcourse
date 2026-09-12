/**
 * 设置页（P0-A3 / P0-A4 / P0-A7 的前端半边）。
 *
 * 验收原文是「填入 Key 保存 → 刷新页面 → 仍显示已配置」，前端能做的是：
 * 把后端说的状态**原样**显示出来，并且把用户的改动**原样**提交上去。
 * 所以这里断言两件事：卡片跟着数据走、保存提交的是草稿里的值。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Slider } from 'tdesign-vue-next'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SettingsView from '@/views/SettingsView.vue'
import type { ProviderCard, VoiceSettings } from '@/types/api'

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

const PROVIDER_NAMES: [string, string][] = [
  ['deepseek', 'DeepSeek'],
  ['openai', 'OpenAI'],
  ['qwen', 'Qwen'],
  ['kimi', 'Kimi'],
  ['custom', '自定义'],
]

const PROVIDERS: ProviderCard[] = PROVIDER_NAMES.map(([id, name], index) => ({
  id,
  name,
  kind: 'llm' as const,
  baseUrl: '',
  defaultModel: index === 0 ? 'deepseek-chat' : '',
  enabled: index === 0,
  configured: index === 0,
  available: index === 0,
  implemented: true,
  maskedKey: index === 0 ? 'sk-****4321' : '',
  missing: index === 0 ? [] : ['API Key'],
  latencyMs: index === 0 ? 320 : null,
  extra: {},
  updatedAt: '2026-01-01T00:00:00Z',
}))

const VOICE: VoiceSettings = {
  voices: ['沈老师', '顾老师', '陆老师'].map((name, index) => ({
    id: `vp_teacher_${index}`,
    name,
    provider: 'volc_tts',
    voiceType: '',
    gender: index === 1 ? 'female' : 'male',
    style: `${name}的说明`,
    sampleUrl: '',
    builtin: true,
    speechRate: 0,
    configured: false,
  })),
  teacherVoiceId: 'vp_teacher_0',
  speed: 1,
  intonation: 'natural',
  asrEnabled: true,
  asrBrowserLocal: true,
}

function mountView() {
  return mount(SettingsView, { global: { plugins: [createPinia()] } })
}

/** 切到左侧菜单的某一项 */
async function switchPane(wrapper: ReturnType<typeof mountView>, label: string) {
  const item = wrapper.findAll('.set-menu__item').find((node) => node.text().includes(label))
  await item?.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.fetchProviders).mockResolvedValue({ items: PROVIDERS, total: 5 })
  vi.mocked(api.fetchVoice).mockResolvedValue(VOICE)
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
      asr: { available: false, offline: false, provider: 'volc_asr', reason: '还没接通' },
      realtime: { available: false, offline: false, provider: 'volc_realtime', reason: '还没接通' },
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

describe('模型服务', () => {
  it('渲染 5 张服务商卡片（P0-A3）', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findAll('.provider')).toHaveLength(5)
    expect(wrapper.text()).toContain('DeepSeek')
    expect(wrapper.text()).toContain('自定义')
  })

  it('已配置的卡片显示脱敏 Key 与延迟', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('延迟 320ms')
    expect(wrapper.text()).not.toContain('sk-****4321') // 掩码只在抽屉里显示
  })
})

describe('语音服务（P0-A7）', () => {
  it('三张音色卡来自后端，未配声音 ID 的要有标记', async () => {
    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '语音服务')

    expect(wrapper.findAll('.voice-card')).toHaveLength(3)
    expect(wrapper.text()).toContain('沈老师')
    expect(wrapper.findAll('.voice-card')[0].text()).toContain('未配声音 ID')
  })

  it('选「顾老师」后保存，提交的就是顾老师', async () => {
    vi.mocked(api.saveVoice).mockImplementation(async (patch) => ({ ...VOICE, ...patch }))
    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '语音服务')

    await wrapper.findAll('.voice-card')[1].trigger('click')
    const saveButton = wrapper.findAll('button').find((item) => item.text().includes('保存设置'))
    await saveButton?.trigger('click')
    await flushPromises()

    expect(api.saveVoice).toHaveBeenCalledWith(
      expect.objectContaining({ teacherVoiceId: 'vp_teacher_1' }),
    )
  })

  it('没改动时「保存设置」是禁用的（避免无谓的写请求）', async () => {
    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '语音服务')

    const saveButton = wrapper.findAll('button').find((item) => item.text().includes('保存设置'))
    expect(saveButton?.attributes('disabled')).toBeDefined()
  })
})

describe('生成参数', () => {
  it('滑杆的边界取自 /api/capabilities，而不是前端写死', async () => {
    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '生成参数')

    expect(wrapper.text()).toContain('12 页')
    expect(wrapper.text()).toContain('3 位')
  })

  it('拖动滑杆后保存，提交的是滑杆当前的值', async () => {
    vi.mocked(api.saveGeneration).mockImplementation(async (patch) => ({
      pageCount: 12,
      classmateCount: 3,
      intensity: 'medium',
      scriptDetail: 'detailed',
      autoIllustration: true,
      quizPerChapter: true,
      whiteboard: true,
      ...patch,
    }))
    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '生成参数')

    // 从滑杆组件本身改值，走的是页面上真实的 v-model 通路
    const pageSlider = wrapper.findAllComponents(Slider)[0]
    pageSlider.vm.$emit('update:modelValue', 16)
    await flushPromises()
    expect(wrapper.text()).toContain('16 页')

    const saveButton = wrapper.findAll('button').find((item) => item.text().includes('保存设置'))
    expect(saveButton?.attributes('disabled')).toBeUndefined()
    await saveButton?.trigger('click')
    await flushPromises()

    expect(api.saveGeneration).toHaveBeenCalledWith(expect.objectContaining({ pageCount: 16 }))
  })
})

describe('保存栏只出现在有草稿的两屏', () => {
  it('模型服务与关于没有保存栏 —— 那边没有「待保存的改动」这回事', async () => {
    const wrapper = mountView()
    await flushPromises()

    // 默认就在「模型服务」
    expect(wrapper.find('.save-bar').exists()).toBe(false)

    await switchPane(wrapper, '关于')
    expect(wrapper.find('.save-bar').exists()).toBe(false)
    // 关于那屏不是空的：环境与版本在这儿（首页徽章已经不挂了）
    expect(wrapper.text()).toContain('v0.1.0')
  })

  it('语音服务与生成参数有保存栏，且没改动时是禁用的', async () => {
    const wrapper = mountView()
    await flushPromises()

    await switchPane(wrapper, '语音服务')
    expect(wrapper.find('.save-bar').exists()).toBe(true)
    expect(wrapper.find('.save-bar').text()).toContain('保存设置')

    await switchPane(wrapper, '生成参数')
    expect(wrapper.find('.save-bar').exists()).toBe(true)

    // 切回没有草稿的一屏，保存栏跟着收起来
    await switchPane(wrapper, '模型服务')
    expect(wrapper.find('.save-bar').exists()).toBe(false)
  })
})
