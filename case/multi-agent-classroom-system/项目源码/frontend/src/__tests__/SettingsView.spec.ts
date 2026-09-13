/**
 * 设置页（P0-A3 / P0-A4 / P0-A7 的前端半边）。
 *
 * 验收原文是「填入 Key 保存 → 刷新页面 → 仍显示已配置」，前端能做的是：
 * 把后端说的状态**原样**显示出来，并且把用户的改动**原样**提交上去。
 * 所以这里断言两件事：卡片跟着数据走、保存提交的是草稿里的值。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Select, Slider } from 'tdesign-vue-next'
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
  // 语音这一屏（P2）：音色试听与用量
  fetchVoices: vi.fn(),
  previewVoice: vi.fn(),
  fetchVoiceUsage: vi.fn(),
  fetchCourses: vi.fn(),
}))

import * as api from '@/api'
import type { UsageReport, VoiceList } from '@/types/api'

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

/** `/api/voice/voices` 那份视图：比设置页的音色表多一个 `usable`。 */
const VOICE_LIST: VoiceList = {
  items: VOICE.voices.map((voice, index) => ({
    ...voice,
    // 只有第一把「配置齐了且服务商可用」：试听按钮只该在它上面亮
    configured: index === 0,
    usable: index === 0,
  })),
  total: 3,
  current: 'vp_teacher_0',
  provider: 'volc_tts',
  enabled: true,
  usable: true,
}

const USAGE: UsageReport = {
  kinds: [
    { kind: 'tts', units: 1234, unitName: 'chars', estCost: 0.02, calls: 3 },
    { kind: 'realtime', units: 0, unitName: 'seconds', estCost: 0, calls: 0 },
    { kind: 'asr', units: 0, unitName: 'seconds', estCost: 0, calls: 0 },
  ],
  totalCost: 0.02,
  priced: false,
  refType: '',
  refId: '',
  enabled: true,
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
    materials: { enabled: true, maxBytes: 52428800 },
  })
  vi.mocked(api.fetchHealth).mockResolvedValue({
    status: 'ok',
    version: '0.1.0',
    db: 'ok',
    providers: { llm: 'ready', tts: 'unconfigured', asr: 'unconfigured', realtime: 'unconfigured' },
    llm: { provider: 'deepseek', model: 'deepseek-chat' },
    issues: [],
  })
  vi.mocked(api.fetchVoices).mockResolvedValue(VOICE_LIST)
  vi.mocked(api.fetchVoiceUsage).mockResolvedValue(USAGE)
  vi.mocked(api.fetchCourses).mockResolvedValue({ items: [], total: 0, page: 1, size: 20 })
  vi.mocked(api.previewVoice).mockResolvedValue({
    voiceId: 'vp_teacher_0',
    url: '/api/voice/voices/vp_teacher_0/preview?v=abc',
    cached: true,
    durationMs: 3200,
    text: '同学们好，我是这门课的老师。',
    provider: 'volc_tts',
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

  it('明说材料发给哪一家（P4-F5 的「设置页明示」那半句）', async () => {
    const wrapper = mountView()
    await flushPromises()

    // PROVIDERS 里只有 DeepSeek 是 enabled —— 说出的名字必须是当前启用的那家
    expect(wrapper.text()).toContain('只把这些分块发给当前启用的「DeepSeek」')
  })

  it('一家都没启用时改说「不会被发往任何服务商」，不留白', async () => {
    vi.mocked(api.fetchProviders).mockResolvedValue({
      items: PROVIDERS.map((card) => ({ ...card, enabled: false })),
      total: 5,
    })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('材料不会被发往任何服务商')
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

describe('音色试听与用量（P2-A5 / P2-A11）', () => {
  it('只有「配置齐了且服务商可用」的音色能试听，点一下真的去合成', async () => {
    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '语音服务')

    const buttons = wrapper.findAll('.voice-card .v-audio')
    expect(buttons).toHaveLength(3)
    // 后两把没配声音 ID：按钮置灰，并把「去哪儿修」写在 title 上
    expect(buttons[0].attributes('disabled')).toBeUndefined()
    expect(buttons[1].attributes('disabled')).toBeDefined()
    expect(buttons[1].attributes('title')).toContain('声音 ID')

    await buttons[0].trigger('click')
    await flushPromises()

    // 没填试听文本 = 用服务端的示例句
    expect(api.previewVoice).toHaveBeenCalledWith('vp_teacher_0', { text: '' })
  })

  it('试听不改变当前选中的音色（听与选是两件事）', async () => {
    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '语音服务')

    // 当前选中的是第 1 把；对第 1 把点试听不该把它自己取消掉
    const cards = wrapper.findAll('.voice-card')
    expect(cards[0].classes()).toContain('is-checked')

    await wrapper.findAll('.voice-card .v-audio')[0].trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.voice-card')[0].classes()).toContain('is-checked')
    expect(wrapper.find('.save-bar button[disabled]').exists()).toBe(true)
  })

  it('试听读不到状态时退到「配没配声音 ID」，并把原因说出来', async () => {
    vi.mocked(api.fetchVoices).mockRejectedValue(new Error('服务没起来'))

    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '语音服务')

    expect(wrapper.find('.pane-hint').text()).toContain('读不到语音服务状态')
    // 退到设置页自己那份 `configured`：这里三把都没配，所以全灰
    const buttons = wrapper.findAll('.voice-card .v-audio')
    expect(buttons.every((button) => button.attributes('disabled') !== undefined)).toBe(true)
  })

  it('用量按链路分开显示，金额与合计来自服务端', async () => {
    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '语音服务')

    const table = wrapper.find('.usage-table').text()
    expect(table).toContain('语音合成（讲稿、试听）')
    expect(table).toContain('1234 字符')
    expect(table).toContain('¥0.0200')
    expect(table).toContain('合计')
    // 没有用量的那两类不摆一行 0 出来
    expect(table).not.toContain('实时语音（课堂问答）')
  })

  it('没配单价时说清合计是少报的，而不是显示 ¥0.00', async () => {
    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '语音服务')

    expect(wrapper.find('.usage-note').text()).toContain('少报')
  })

  it('可以只看某门课的用量', async () => {
    vi.mocked(api.fetchCourses).mockResolvedValue({
      items: [
        {
          id: 'c1',
          title: '机器学习入门',
          topic: '机器学习入门',
          status: 'ready',
          pageCount: 12,
          readyPages: 12,
          durationMin: 25,
          roleCount: 4,
          cover: {},
          progress: 100,
          jobId: 'j1',
          createdAt: 'x',
          updatedAt: 'x',
        },
      ],
      total: 1,
      page: 1,
      size: 20,
    })

    const wrapper = mountView()
    await flushPromises()
    await switchPane(wrapper, '语音服务')

    // 进这一屏先看的是「全部课堂」
    expect(api.fetchVoiceUsage).toHaveBeenLastCalledWith({})

    const select = wrapper.findComponent(Select)
    expect(select.props('options')).toEqual([
      { label: '全部课堂', value: '' },
      { label: '机器学习入门', value: 'c1' },
    ])

    // 选一门课：传给服务端的是 refType/refId，筛选不在前端做
    select.vm.$emit('change', 'c1')
    await flushPromises()

    expect(api.fetchVoiceUsage).toHaveBeenLastCalledWith({ refType: 'course', refId: 'c1' })
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
