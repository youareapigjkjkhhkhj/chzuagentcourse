/**
 * 首页生成入口与「最近课堂」（P1-A1 / P1-A10 / P1-F1 的前端半边）。
 *
 * 首页要证明的四件事：
 *
 * 1. **输入一个主题就能开工**：回车或点按钮都行，示例标签负责把主题填进去。
 * 2. **开出去的课停在大纲确认点**：首页是界面上唯一的生成入口，`confirmOutline`
 *    只能由这里带上 —— 工作台的大纲树要停在那一点才谈得上编辑（F1-3）。
 * 3. **卡片上的数字是服务端给的**。页数、时长、状态、进度都照抄 `GET /api/courses`，
 *    页面不自己算一份 —— 自己算的那份迟早和详情页对不上（A10 要防的就是这个）。
 * 4. **生成中的卡片会自动刷新**，靠的是轮询 REST，而不是把 68% 慢慢往上加。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  fetchCourses: vi.fn(),
  startGeneration: vi.fn(),
  deleteCourse: vi.fn(),
  fetchCapabilities: vi.fn(),
  fetchHealth: vi.fn(),
  fetchGeneration: vi.fn(),
  fetchProviders: vi.fn(),
  fetchVoice: vi.fn(),
  fetchRoles: vi.fn(),
}))

import * as api from '@/api'
import type { CourseCard, CourseList } from '@/types/api'
import IndexView from '@/views/IndexView.vue'

const CARD: CourseCard = {
  id: 'c1',
  title: '机器学习入门：从感知机到神经网络',
  topic: '机器学习入门',
  status: 'ready',
  pageCount: 12,
  readyPages: 12,
  durationMin: 25,
  roleCount: 4,
  cover: {},
  progress: 100,
  jobId: 'j1',
  createdAt: '2026-09-12T02:00:00Z',
  updatedAt: '2026-09-12T02:10:00Z',
}

const LIST: CourseList = { items: [CARD], total: 1, page: 1, size: 12 }

const CAPABILITIES = {
  env: 'testing',
  version: '0.1.0',
  capabilities: {
    llm: { available: true, offline: true, provider: 'mock', reason: '' },
    tts: { available: false, offline: true, provider: 'mock', reason: '' },
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
  materials: { enabled: true, maxBytes: 52428800 },
}

async function mountHome() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', name: 'index', component: IndexView },
    { path: '/workbench', name: 'workbench', component: { template: '<div>工作台</div>' } },
  ] })
  await router.push('/')
  await router.isReady()

  const wrapper = mount(IndexView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.fetchCourses).mockResolvedValue(LIST)
  vi.mocked(api.fetchGeneration).mockResolvedValue({
    pageCount: 12,
    classmateCount: 3,
    intensity: 'medium',
    scriptDetail: 'detailed',
    autoIllustration: true,
    quizPerChapter: true,
    whiteboard: true,
  })
  vi.mocked(api.fetchCapabilities).mockResolvedValue(CAPABILITIES as never)
  vi.mocked(api.fetchHealth).mockResolvedValue({} as never)
  vi.mocked(api.fetchProviders).mockResolvedValue({ items: [], total: 0 })
  vi.mocked(api.fetchVoice).mockResolvedValue({ voices: [] } as never)
  vi.mocked(api.fetchRoles).mockResolvedValue({ items: [], total: 0 })
  vi.mocked(api.startGeneration).mockResolvedValue({
    courseId: 'c9',
    jobId: 'j9',
    status: 'queued',
    stream: '/api/courses/generate/j9/stream',
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('首屏徽章与页脚', () => {
  it('徽章说的是这门课是什么（照原型那句话），环境与版本挪到页脚', async () => {
    const { wrapper } = await mountHome()

    expect(wrapper.find('.hero__badge').text()).toContain('开源 · 多智能体 · 一键生成互动课堂')
    // 原来挂在徽章上的两个数没有丢，只是换到了不起眼的地方
    const footer = wrapper.find('footer').text()
    expect(footer).toContain('testing')
    expect(footer).toContain('v0.1.0')
  })
})

describe('生成入口（F1-1）', () => {
  it('示例主题点一下就填进输入框', async () => {
    const { wrapper } = await mountHome()

    const chip = wrapper.findAll('.example-chip')[0]
    await chip.trigger('click')

    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe(
      chip.text().trim(),
    )
  })

  it('输入主题后点「开始生成」：打的是生成接口，然后进工作台', async () => {
    const { wrapper, router } = await mountHome()
    await wrapper.find('textarea').setValue('机器学习入门')

    const button = wrapper.findAll('button').find((node) => node.text().includes('开始生成'))
    await button?.trigger('click')
    await flushPromises()

    // 带上 confirmOutline（F1-3）：这一门课的第一个停点是工作台的大纲确认
    expect(api.startGeneration).toHaveBeenCalledWith({
      topic: '机器学习入门',
      mode: 'lecture',
      confirmOutline: true,
    })
    expect(router.currentRoute.value.name).toBe('workbench')
    expect(router.currentRoute.value.query).toMatchObject({ course: 'c9', job: 'j9' })
  })

  it('研讨模式会跟着请求一起发出去', async () => {
    const { wrapper } = await mountHome()
    await wrapper.find('textarea').setValue('宏观经济学')

    // 原型上那两个工具按钮
    const seminar = wrapper.findAll('.gen-tool').find((node) => node.text().includes('研讨模式'))
    await seminar?.trigger('click')
    const button = wrapper.findAll('button').find((node) => node.text().includes('开始生成'))
    await button?.trigger('click')
    await flushPromises()

    // 模式与暂停点一起发：研讨模式也照样先停在确认点
    expect(api.startGeneration).toHaveBeenCalledWith({
      topic: '宏观经济学',
      mode: 'seminar',
      confirmOutline: true,
    })
  })

  it('主题是空的就不发请求（空主题在服务端也过不了 P1-F1 的清洗）', async () => {
    const { wrapper } = await mountHome()

    await wrapper.find('textarea').setValue('   ')
    const button = wrapper.findAll('button').find((node) => node.text().includes('开始生成'))
    await button?.trigger('click')
    await flushPromises()

    expect(api.startGeneration).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请先输入')
  })

  it('「预计生成 N 页」读的是设置页保存的页数', async () => {
    vi.mocked(api.fetchGeneration).mockResolvedValue({
      pageCount: 16,
      classmateCount: 3,
      intensity: 'medium',
      scriptDetail: 'detailed',
      autoIllustration: true,
      quizPerChapter: true,
      whiteboard: true,
    })
    const { wrapper } = await mountHome()

    expect(wrapper.text()).toContain('预计生成 16 页')
  })
})

describe('最近课堂（A10）', () => {
  it('卡片上的页数、时长、状态照抄接口给的那份', async () => {
    const { wrapper } = await mountHome()

    const card = wrapper.find('.course-card')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('机器学习入门：从感知机到神经网络')
    expect(card.text()).toContain('12 页课件')
    expect(card.text()).toContain('25 分钟')
    expect(card.text()).toContain('已生成')
  })

  it('生成中的卡片显示服务端给的百分比', async () => {
    vi.mocked(api.fetchCourses).mockResolvedValue({
      items: [{ ...CARD, status: 'generating', progress: 68, readyPages: 7 }],
      total: 1,
      page: 1,
      size: 12,
    })
    const { wrapper } = await mountHome()

    expect(wrapper.find('.course-card').text()).toContain('生成中 68%')
  })

  it('点卡片进工作台，带着课程与任务 id', async () => {
    const { wrapper, router } = await mountHome()

    await wrapper.find('.course-card').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('workbench')
    expect(router.currentRoute.value.query).toMatchObject({ course: 'c1', job: 'j1' })
  })

  it('一门课都没有时给空状态，而不是四张假卡片', async () => {
    vi.mocked(api.fetchCourses).mockResolvedValue({ items: [], total: 0, page: 1, size: 12 })
    const { wrapper } = await mountHome()

    expect(wrapper.findAll('.course-card')).toHaveLength(0)
    expect(wrapper.text()).toContain('还没有生成的课堂')
  })

  it('有课在生成时就定时重问一次列表，进度不是页面上爬出来的', async () => {
    vi.useFakeTimers()
    vi.mocked(api.fetchCourses).mockResolvedValue({
      items: [{ ...CARD, status: 'generating', progress: 68 }],
      total: 1,
      page: 1,
      size: 12,
    })
    await mountHome()
    vi.mocked(api.fetchCourses).mockClear()

    await vi.advanceTimersByTimeAsync(5000)

    expect(api.fetchCourses).toHaveBeenCalled()
  })

  it('全部就绪之后不再轮询（没有变化就没有请求）', async () => {
    vi.useFakeTimers()
    await mountHome()
    vi.mocked(api.fetchCourses).mockClear()

    await vi.advanceTimersByTimeAsync(15000)

    expect(api.fetchCourses).not.toHaveBeenCalled()
  })
})
