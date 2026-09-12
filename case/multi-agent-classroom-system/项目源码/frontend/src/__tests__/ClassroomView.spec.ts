/**
 * 课堂演示页 = 已生成课程的只读预览。
 *
 * 这一页补的是 P1 的欠账：课程号从地址栏来，幻灯片、讲稿、大纲都取服务端那份。
 * 测试盯的是四件事：
 * 1. 舞台按页放映，翻页只走「已生成的页」，到头就停（不空转、不越界）
 * 2. 大纲是真的，点一下跳到那一页，当前页高亮、翻过的打勾
 * 3. 没给课程号 / 读失败时说的是人话，不假装课是空的
 * 4. 没有音频与课堂运行时这件事，页面上照实写着，不摆一个看起来很热闹的假课堂
 */

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  fetchCourse: vi.fn(),
  fetchOutline: vi.fn(),
  fetchCourses: vi.fn(),
  // 顶栏那几个标签要的成员数来自设置 store（`loadRoles`）
  fetchRoles: vi.fn(),
}))

import * as api from '@/api'
import type { AgentRole, CourseDetail, CoursePageItem, OutlineTree } from '@/types/api'
import { ApiError } from '@/api/client'
import ClassroomView from '@/views/ClassroomView.vue'

function page(no: number, title: string, beat: string): CoursePageItem {
  return {
    id: `p${no}`,
    courseId: 'c1',
    chapterNo: no > 2 ? 1 : 0,
    pageNo: no,
    kind: 'concept',
    title,
    status: 'ready',
    rev: 1,
    dsl: {
      kind: 'concept',
      title,
      bullets: [{ text: `${title}的要点`, emphasis: [] }],
      narration: [{ beatId: `p${no}-b1`, text: beat, estSec: 6 }],
    },
  }
}

const PAGES = [
  page(1, '机器学习入门', '这门课我们从身边的例子说起。'),
  page(2, '课程大纲', '这一门课一共四章，先看整体。'),
  page(3, '感知机：最简单的神经元', '感知机接收多个输入，各自乘以权重后求和。'),
]

const DETAIL: CourseDetail = {
  id: 'c1',
  title: '机器学习入门',
  topic: '机器学习入门',
  subtitle: '从感知机到神经网络',
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
  chapters: [],
  meta: {},
  pages: PAGES,
}

const TREE: OutlineTree = {
  courseId: 'c1',
  title: '机器学习入门',
  subtitle: '',
  status: 'ready',
  pageCount: 12,
  jobId: 'j1',
  jobStatus: 'done',
  progress: 100,
  confirmable: false,
  front: [
    { pageNo: 1, kind: 'cover', title: '机器学习入门', status: 'ready', rev: 1 },
    { pageNo: 2, kind: 'outline', title: '课程大纲', status: 'ready', rev: 1 },
  ],
  back: [],
  chapters: [
    {
      no: 1,
      title: '第一章 · 什么是机器学习',
      summary: '',
      points: [],
      discussion: [],
      pages: [
        { pageNo: 3, kind: 'concept', title: '感知机：最简单的神经元', status: 'ready', rev: 1 },
      ],
    },
  ],
}

const ROLES: AgentRole[] = [
  ['t1', '沈老师', 'teacher'],
  ['s1', '林晓', 'student'],
  ['s2', '陈默', 'student'],
  ['s3', '苏雨', 'student'],
].map(([id, name, role]) => ({
  id,
  code: id,
  name,
  role: role as AgentRole['role'],
  avatarColor: '#0052d9',
  voiceProfileId: '',
  builtin: true,
  persona: { tone: '', style: '', speechRate: 1, pitch: 1, systemHint: '' },
}))

async function mountClassroom(query: Record<string, string> = { course: 'c1' }) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'index', component: { template: '<div>首页</div>' } },
      { path: '/classroom', name: 'classroom', component: ClassroomView },
      { path: '/settings', name: 'settings', component: { template: '<div>设置</div>' } },
    ],
  })
  await router.push({ path: '/classroom', query })
  await router.isReady()

  const wrapper = mount(ClassroomView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return wrapper
}

/** 舞台上的那一页（`.preview__slide`），没有就是空状态。 */
const slide = (wrapper: Awaited<ReturnType<typeof mountClassroom>>) =>
  wrapper.find('.preview__slide')

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.fetchCourse).mockResolvedValue(DETAIL)
  vi.mocked(api.fetchOutline).mockResolvedValue(TREE)
  vi.mocked(api.fetchCourses).mockResolvedValue({ items: [], total: 0, page: 1, size: 20 })
  // 角色表由组件自己 `loadRoles()` 拉（种子里的 1 教师 + 3 同学）
  vi.mocked(api.fetchRoles).mockResolvedValue({ items: ROLES, total: ROLES.length })
})

describe('课堂演示：按页放映一门已生成的课', () => {
  it('带课程号进来，舞台上是第 1 页，顶栏是这门课的标题与成员数', async () => {
    const wrapper = await mountClassroom()

    expect(api.fetchCourse).toHaveBeenCalledWith('c1', { withPages: true })
    expect(api.fetchOutline).toHaveBeenCalledWith('c1')
    expect(wrapper.find('.cls-header__title').text()).toBe('机器学习入门')
    expect(wrapper.find('.cls-header__meta').text()).toContain('只读预览')
    expect(wrapper.find('.cls-header__meta').text()).toContain('1 位教师')
    expect(wrapper.find('.cls-header__meta').text()).toContain('3 位 AI 同学')

    expect(slide(wrapper).text()).toContain('机器学习入门')
    // 页数是**服务端那份**（12），不是「拉了 3 页下来」那个 3
    expect(wrapper.find('.page-indicator').text()).toContain('第 1 / 12 页')
  })

  it('字幕条放的是这一页的讲稿，不是一句写死的占位', async () => {
    const wrapper = await mountClassroom()

    expect(wrapper.find('.subtitle').text()).toContain('这门课我们从身边的例子说起。')
  })

  it('翻页走到头就停：第一页没有上一页、最后一页没有下一页', async () => {
    const wrapper = await mountClassroom()

    const [prev, next] = wrapper.findAll('.player-bar .t-button')
    expect(prev.attributes('disabled')).toBeDefined()

    await next.trigger('click')
    await flushPromises()
    expect(wrapper.find('.page-indicator').text()).toContain('第 2 / 12 页')
    expect(wrapper.find('.subtitle').text()).toContain('这一门课一共四章')

    await next.trigger('click')
    await flushPromises()
    expect(wrapper.find('.page-indicator').text()).toContain('第 3 / 12 页')

    // 第 3 页是拉下来的最后一页：再点不该翻到一片空白
    const lastNext = wrapper.findAll('.player-bar .t-button')[1]
    expect(lastNext.attributes('disabled')).toBeDefined()
    await lastNext.trigger('click')
    await flushPromises()
    expect(wrapper.find('.page-indicator').text()).toContain('第 3 / 12 页')

    await wrapper.findAll('.player-bar .t-button')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.page-indicator').text()).toContain('第 2 / 12 页')
  })

  it('大纲是真的：按章展开，点一下就跳到那一页，当前页高亮、翻过的打勾', async () => {
    const wrapper = await mountClassroom()

    // 切到「课程大纲」页签
    const outlineTab = wrapper.findAll('.t-tabs__nav-item').find((tab) =>
      tab.text().includes('课程大纲'),
    )
    await outlineTab?.trigger('click')
    await flushPromises()

    const outline = wrapper.find('.outline')
    expect(outline.text()).toContain('第一章 · 什么是机器学习')
    expect(outline.text()).toContain('感知机：最简单的神经元')

    // 开篇（封面/大纲页）没有章标题，但页在
    expect(outline.text()).toContain('机器学习入门')

    const target = wrapper
      .findAll('.outline__page')
      .find((row) => row.text().includes('感知机'))
    await target?.trigger('click')
    await flushPromises()

    expect(wrapper.find('.page-indicator').text()).toContain('第 3 / 12 页')
    expect(wrapper.find('.outline__page.is-current').text()).toContain('感知机')
    // 翻过的两页打了勾，当前页没有
    expect(wrapper.findAll('.outline__page .done')).toHaveLength(2)
  })

  it('没给课程号时说人话，并指路去哪儿找课', async () => {
    const wrapper = await mountClassroom({})

    expect(api.fetchCourse).not.toHaveBeenCalled()
    expect(wrapper.find('.preview__slide').exists()).toBe(false)
    const empty = wrapper.find('.slide').text()
    expect(empty).toContain('还没有可讲授的课程')
    expect(empty).toContain('预览课堂')
    // 「课堂运行时在 P3」这件事不能因为页面接上了就被抹掉
    expect(empty).toContain('课堂运行时')
  })

  it('读失败时说的是「没读出来」，不把 404 画成「这门课是空的」', async () => {
    vi.mocked(api.fetchCourse).mockRejectedValue(new ApiError(40401, '课程不存在'))

    const wrapper = await mountClassroom()

    expect(wrapper.find('.slide').text()).toContain('这门课没读出来')
    expect(wrapper.find('.slide').text()).toContain('课程不存在')
  })

  it('有课在预览时，提示条说清哪三件事还没有', async () => {
    const wrapper = await mountClassroom()

    const banner = wrapper.find('.cls-banner').text()
    expect(banner).toContain('只读预览')
    expect(banner).toContain('P2')
    expect(banner).toContain('P3')
  })
})
