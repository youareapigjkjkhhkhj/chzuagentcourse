/**
 * 路由与四页渲染（P0-A2：顶栏四页导航可跳转且不白屏、无控制台报错）。
 *
 * 「不白屏」在测试里的等价物是：每个路由都能挂载出内容，且过程中没有
 * 未捕获的异常。真正的控制台报错（Vue 的 warn/error）在这里会被
 * `console.error` 的 spy 抓住 —— 只断言「有文字」会漏掉组件内部炸掉
 * 但外层还有内容的情况。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '@/App.vue'
import { useSettingsStore } from '@/stores/settings'

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
  // 课堂演示页在有 `?course=` 时才拉这几样；这里补上是为了让那份替身完整 ——
  // 少一个导出，import 到它的组件拿到的是 undefined，报错会指向别处
  fetchCourses: vi.fn(),
  fetchCourse: vi.fn(),
  fetchOutline: vi.fn(),
  fetchAudioManifest: vi.fn(),
  narrateCourse: vi.fn(),
  // 语音：设置页的试听与用量（pane 切过去才拉）
  fetchVoices: vi.fn(),
  previewVoice: vi.fn(),
  fetchVoiceUsage: vi.fn(),
  // 实时语音的地址要到开麦克风那一刻才取
  realtimeUrl: vi.fn(() => 'ws://localhost/ws/voice/realtime'),
}))

import * as api from '@/api'

/** 一份「什么都还没配」的环境快照：最容易暴露空状态处理问题的情形。 */
function stubEmptyEnvironment() {
  vi.mocked(api.fetchProviders).mockResolvedValue({ items: [], total: 0 })
  vi.mocked(api.fetchVoice).mockResolvedValue({
    voices: [],
    teacherVoiceId: '',
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
  vi.mocked(api.fetchCourses).mockResolvedValue({ items: [], total: 0, page: 1, size: 20 })
  // 课堂页即使没有 `?course=` 也会读一次清单（没课号时读的是空串），给一份空的
  vi.mocked(api.fetchAudioManifest).mockResolvedValue({
    courseId: '',
    voiceId: '',
    speed: null,
    rate: 1,
    tone: '',
    provider: '',
    simulated: false,
    enabled: false,
    available: false,
    fallback: 'text',
    reason: 'voice_disabled',
    beatCount: 0,
    readyCount: 0,
    beats: [],
    running: false,
  })
  vi.mocked(api.fetchCapabilities).mockResolvedValue({
    env: 'testing',
    version: '0.1.0',
    capabilities: {
      llm: { available: false, offline: true, provider: 'mock', reason: '未配置文本模型' },
      tts: { available: false, offline: true, provider: 'mock', reason: '没有声音' },
      asr: { available: false, offline: true, provider: 'mock', reason: '学生无法语音发言' },
      realtime: { available: false, offline: true, provider: 'mock', reason: '文字降级链路' },
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
    providers: {
      llm: 'unconfigured',
      tts: 'unconfigured',
      asr: 'unconfigured',
      realtime: 'unconfigured',
    },
    llm: { provider: 'mock', model: '' },
    issues: [{ level: 'warning', code: 'tts_offline', message: '语音合成未配置' }],
  })
}

/**
 * 测试里的路由表（用 memory history，避免污染 jsdom 的地址栏）。
 * 它是真实路由的副本 —— 下面的 `与真实路由表一致` 就是为了防副本漂移：
 * 顶栏高亮认的是 `route.name`，名字对不上会「页面换了、顶栏不亮」。
 */
const ROUTES = [
  { path: '/', name: 'index', component: () => import('@/views/IndexView.vue') },
  { path: '/workbench', name: 'workbench', component: () => import('@/views/WorkbenchView.vue') },
  { path: '/classroom', name: 'classroom', component: () => import('@/views/ClassroomView.vue') },
  { path: '/classroom/record', name: 'classroom-record', component: () => import('@/views/ClassroomRecordView.vue') },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
] as const

async function mountAt(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [...ROUTES] })
  await router.push(path)
  await router.isReady()

  const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return wrapper
}

let errorSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  setActivePinia(createPinia())
  stubEmptyEnvironment()
  errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  errorSpy.mockRestore()
})

describe('顶栏', () => {
  it('测试用的路由表与真实路由表一致', async () => {
    const { default: realRouter } = await import('@/router')

    for (const route of ROUTES) {
      const real = realRouter.resolve(route.path)
      expect(real.name, `${route.path} 的路由名`).toBe(route.name)
    }
  })

  it('四个导航项都在，当前页高亮', async () => {
    const wrapper = await mountAt('/settings')

    const labels = wrapper.findAll('.nav-item').map((item) => item.text())
    expect(labels).toEqual(['首页', '工作台', '课堂演示', '设置'])
    expect(wrapper.find('.nav-item.is-active').text()).toBe('设置')
  })

  it('导航到另一页会真的换视图（不是空壳）', async () => {
    const wrapper = await mountAt('/')

    expect(wrapper.text()).toContain('输入一个主题')
    const workbench = wrapper.findAll('.nav-item').find((item) => item.text() === '工作台')
    await workbench?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('工作台')
  })
})

describe('四个页面', () => {
  // 断言的是「这一页独有的东西」，换个页面就不会出现的文字 ——
  // 用「设置」这类到处都有的词，导航挂了测试也照样绿
  it.each([
    ['/', '输入一个主题'],
    ['/workbench', '课程生成 Agent'],
    ['/classroom', '导出课件'],
    ['/settings', '模型服务商'],
  ])('%s 有内容且不报错', async (path, expected) => {
    const wrapper = await mountAt(path)

    expect(wrapper.text()).toContain(expected)
    expect(errorSpy).not.toHaveBeenCalled()
  })

  it('环境全空时首页仍然渲染得出（说清「不可用」，而不是白屏）', async () => {
    const wrapper = await mountAt('/')
    const store = useSettingsStore()
    await store.loadAll()
    await flushPromises()

    expect(wrapper.text()).toContain('环境自检')
    expect(errorSpy).not.toHaveBeenCalled()
  })
})
