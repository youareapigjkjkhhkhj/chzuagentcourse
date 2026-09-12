/**
 * 工作台（P1-A3 / A4 / A7 / A8 / A9 / A11 / B5）。
 *
 * 每条验收在这里都有对应的一个断言，主线是同一件事：
 * **屏幕上出现的每个状态，都能追到服务端的一次响应或一帧事件**。
 * 所以测试里既喂 SSE 事件、也打桩 REST，然后断言界面跟着哪一份走 ——
 * 特别是「一份数据都没有的时候，界面上不该凭空出现百分比」（B5）。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  fetchCourse: vi.fn(),
  fetchOutline: vi.fn(),
  confirmOutline: vi.fn(),
  fetchPage: vi.fn(),
  savePage: vi.fn(),
  rewritePage: vi.fn(),
  fetchVersions: vi.fn(),
  fetchJob: vi.fn(),
  cancelJob: vi.fn(),
  retryStep: vi.fn(),
  startGeneration: vi.fn(),
  fetchCourses: vi.fn(),
  streamUrl: (jobId: string) => `/api/courses/generate/${jobId}/stream`,
}))

import * as api from '@/api'
import type { CourseDetail, CoursePageItem, GenJobView, OutlineTree } from '@/types/api'
import OutlineAddDialog from '@/components/workbench/OutlineAddDialog.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  readonly url: string
  closed = false
  onerror: ((event: unknown) => void) | null = null
  private listeners = new Map<string, ((event: { data: string }) => void)[]>()

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(name: string, handler: (event: { data: string }) => void) {
    const list = this.listeners.get(name) ?? []
    list.push(handler)
    this.listeners.set(name, list)
  }

  close() {
    this.closed = true
  }

  emit(name: string, payload: unknown) {
    for (const handler of this.listeners.get(name) ?? []) {
      handler({ data: JSON.stringify(payload) })
    }
  }
}

const DETAIL: CourseDetail = {
  id: 'c1',
  title: '机器学习入门',
  topic: '机器学习入门',
  subtitle: '从感知机到神经网络',
  status: 'generating',
  pageCount: 12,
  readyPages: 6,
  durationMin: 25,
  roleCount: 4,
  cover: {},
  progress: 15,
  jobId: 'j1',
  createdAt: 'x',
  updatedAt: 'x',
  chapters: [],
  meta: {},
}

const TREE: OutlineTree = {
  courseId: 'c1',
  title: '机器学习入门',
  subtitle: '',
  status: 'generating',
  jobId: 'j1',
  jobStatus: 'running',
  progress: 15,
  confirmable: false,
  pageCount: 6,
  front: [
    { pageNo: 1, kind: 'cover', title: '机器学习入门', status: 'ready', rev: 1 },
    { pageNo: 2, kind: 'outline', title: '课程大纲', status: 'ready', rev: 1 },
  ],
  back: [{ pageNo: 6, kind: 'summary', title: '课程小结', status: 'pending', rev: 0 }],
  chapters: [
    {
      no: 1,
      title: '第一章 · 什么是机器学习',
      summary: '概览',
      points: ['讨论点'],
      discussion: [],
      pages: [
        { pageNo: 3, kind: 'concept', title: '课程导入', status: 'ready', rev: 1 },
        { pageNo: 4, kind: 'concept', title: '监督与非监督', status: 'pending', rev: 0 },
      ],
    },
    {
      no: 2,
      title: '第二章 · 线性模型',
      summary: '',
      points: [],
      discussion: [],
      pages: [
        { pageNo: 5, kind: 'concept', title: '线性回归', status: 'pending', rev: 0 },
        { pageNo: 6, kind: 'quiz', title: '第二章 · 随堂测验', status: 'pending', rev: 0 },
      ],
    },
  ],
}

/**
 * 停在「大纲确认点」的同一棵树。
 *
 * `confirmable` = 任务正 paused 等着确认 —— 增删改序**只在这个时候开着**，
 * 因为生成跑起来之后服务端一律 409（「这次生成已经结束，大纲不能再改」）。
 */
const PAUSED: OutlineTree = { ...TREE, jobStatus: 'paused', confirmable: true }

const PAGE: CoursePageItem = {
  id: 'p3',
  courseId: 'c1',
  chapterNo: 1,
  pageNo: 3,
  kind: 'concept',
  title: '课程导入',
  status: 'ready',
  rev: 1,
  dsl: {
    kind: 'concept',
    title: '课程导入',
    subtitle: '身边的机器学习',
    bullets: [{ text: '从垃圾邮件过滤说起', emphasis: [] }],
    narration: [{ beatId: 'p3-b1', text: '我们先从一个熟悉的场景说起。', estSec: 6 }],
    visual: { type: 'diagram', desc: '一封被标记的邮件' },
  },
}

const JOB: GenJobView = {
  id: 'j1',
  courseId: 'c1',
  status: 'running',
  progress: 0,
  totalMs: 0,
  totalTokens: 0,
  options: {},
  error: '',
  createdAt: 'x',
  updatedAt: 'x',
  steps: [
    ['s1', 'parse', '解析需求与受众画像', 'done'],
    ['s2', 'outline', '生成课程大纲', 'done'],
    ['s3', 'write', '撰写页面内容与讲稿', 'running'],
    ['s4', 'quiz', '设计讨论问题与随堂测验', 'wait'],
    ['s5', 'tts', '合成教师语音', 'wait'],
    ['s6', 'assemble', '装配课程', 'wait'],
  ].map(([id, type, title, status], index) => ({
    id,
    jobId: 'j1',
    seq: index + 1,
    type: type as never,
    title,
    status: status as never,
    detail: {},
    durationMs: status === 'done' ? 6000 : 0,
    tokens: 0,
    error: '',
    startedAt: null,
    finishedAt: null,
  })),
  currentStep: null,
  failedSteps: [],
  retryable: false,
}

async function mountWorkbench(query: Record<string, string> = { course: 'c1', job: 'j1' }) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/workbench', name: 'workbench', component: WorkbenchView },
      { path: '/classroom', name: 'classroom', component: { template: '<div>课堂</div>' } },
    ],
  })
  await router.push({ path: '/workbench', query })
  await router.isReady()

  const wrapper = mount(WorkbenchView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return { wrapper, router }
}

type Wrapper = Awaited<ReturnType<typeof mountWorkbench>>['wrapper']

/** 找一页树节点（按标题）。找不到就当场报错 —— 让人看见是哪一页没画出来。 */
function findPage(wrapper: Wrapper, title: string) {
  const node = wrapper.findAll('.tree-page').find((row) => row.text().includes(title))
  if (!node) throw new Error(`大纲树里没有「${title}」`)
  return node
}

/** 屏幕上从上到下的每一页的标题 —— 拖动排序断言的就是这个顺序。 */
const pageTitles = (wrapper: Wrapper) =>
  wrapper.findAll('.tree-page .p-title').map((row) => row.text())

/** 找一章的标题行（按章名里的关键词）。 */
function chapterTitle(wrapper: Wrapper, keyword: string) {
  const node = wrapper.findAll('.tree-chapter__title').find((row) => row.text().includes(keyword))
  if (!node) throw new Error(`大纲树里没有「${keyword}」这一章`)
  return node
}

/** 中间那一栏标题行上的按钮（「确认大纲」/「章节」）。 */
function headButton(wrapper: Wrapper, label: string) {
  const node = wrapper.findAll('.wb-outline__head button').find((row) => row.text().includes(label))
  if (!node) throw new Error(`大纲栏上没有「${label}」按钮`)
  return node
}

beforeEach(() => {
  setActivePinia(createPinia())
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)

  vi.mocked(api.fetchCourse).mockResolvedValue(DETAIL)
  vi.mocked(api.fetchOutline).mockResolvedValue(TREE)
  vi.mocked(api.fetchJob).mockResolvedValue(JOB)
  vi.mocked(api.fetchPage).mockResolvedValue(PAGE)
  vi.mocked(api.fetchVersions).mockResolvedValue({ items: [] })
  vi.mocked(api.savePage).mockResolvedValue({ ...PAGE, rev: 2 })
  vi.mocked(api.rewritePage).mockResolvedValue({ page: { ...PAGE, rev: 2 }, tokens: 100, model: 'stub' })
  // `resumed` 是后端确认大纲响应里的字段：这次提交之后管线有没有接着往下跑
  vi.mocked(api.confirmOutline).mockResolvedValue({
    ...TREE,
    pageCount: 11,
    confirmable: false,
    resumed: true,
  })
  vi.mocked(api.cancelJob).mockResolvedValue({ ...JOB })
  vi.mocked(api.retryStep).mockResolvedValue({ jobId: 'j1', stepId: 's3', status: 'queued' })
})

describe('打开工作台', () => {
  it('读的是这门课的大纲与任务，而不是内存里的上次状态', async () => {
    const { wrapper } = await mountWorkbench()

    expect(api.fetchOutline).toHaveBeenCalledWith('c1')
    expect(api.fetchJob).toHaveBeenCalledWith('j1')
    expect(wrapper.text()).toContain('机器学习入门')
    expect(wrapper.text()).toContain('课程生成 Agent')
  })

  it('没有选课的时候给空状态，不去打接口', async () => {
    const { wrapper } = await mountWorkbench({})

    expect(api.fetchOutline).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('还没有选择课程')
  })

  it('任务卡按服务端给的顺序列出六步，每步状态跟着走', async () => {
    const { wrapper } = await mountWorkbench()

    const steps = wrapper.findAll('.task-step')
    expect(steps.map((row) => row.text())).toEqual([
      expect.stringContaining('解析需求与受众画像'),
      expect.stringContaining('生成课程大纲'),
      expect.stringContaining('撰写页面内容与讲稿'),
      expect.stringContaining('设计讨论问题与随堂测验'),
      expect.stringContaining('合成教师语音'),
      expect.stringContaining('装配课程'),
    ])
    expect(steps[0].classes()).toContain('is-done')
    expect(steps[2].classes()).toContain('is-running')
    expect(steps[3].classes()).toContain('is-waiting')
  })

  it('已完成的那步显示服务端记的耗时', async () => {
    const { wrapper } = await mountWorkbench()

    expect(wrapper.findAll('.task-step')[0].text()).toContain('6s')
  })
})

describe('进度只认服务端（B5）', () => {
  it('一次数据都没拿到时，进度是「—」而不是一个会自己爬的数字', async () => {
    vi.mocked(api.fetchJob).mockRejectedValue(new Error('连不上'))
    const { wrapper } = await mountWorkbench()

    expect(wrapper.find('.wb-progress').text()).toContain('—')
    expect(wrapper.find('.wb-progress').text()).not.toMatch(/\d+%/)
  })

  it('SSE 推来多少就是多少：20% 不会自己涨到 21%', async () => {
    vi.mocked(api.fetchJob).mockRejectedValue(new Error('连不上'))
    const { wrapper } = await mountWorkbench()

    FakeEventSource.instances[0].emit('step.progress', {
      stepId: 's3',
      type: 'write',
      percent: 50,
      progress: 20,
      detail: { pageNo: 7 },
    })
    await flushPromises()

    expect(wrapper.find('.wb-progress').text()).toContain('20%')
  })
})

describe('大纲树四态（A4）', () => {
  it('待生成的页面显示「待生成」，已完成的不再显示进度', async () => {
    const { wrapper } = await mountWorkbench()

    expect(findPage(wrapper, '课程导入').text()).toContain('完成')
    expect(findPage(wrapper, '监督与非监督').text()).toContain('待生成')
  })

  it('正在写的那一页显示「生成中」，其余仍是「待生成」', async () => {
    const { wrapper } = await mountWorkbench()

    FakeEventSource.instances[0].emit('step.progress', {
      stepId: 's3',
      type: 'write',
      percent: 30,
      progress: 30,
      detail: { pageNo: 5 },
    })
    await flushPromises()

    expect(findPage(wrapper, '线性回归').text()).toContain('生成中')
    expect(findPage(wrapper, '监督与非监督').text()).toContain('待生成')
  })

  it('page.ready 之后那一页变「完成」', async () => {
    const { wrapper } = await mountWorkbench()

    FakeEventSource.instances[0].emit('page.ready', { pageNo: 4, kind: 'concept', title: '监督与非监督' })
    await flushPromises()

    expect(findPage(wrapper, '监督与非监督').text()).toContain('完成')
  })

  it('选中的那一页显示「编辑中」', async () => {
    const { wrapper } = await mountWorkbench()

    await findPage(wrapper, '课程导入').trigger('click')
    await flushPromises()

    expect(findPage(wrapper, '课程导入').classes()).toContain('is-selected')
    expect(findPage(wrapper, '课程导入').text()).toContain('编辑中')
  })

  it('失败的页面显示「失败」', async () => {
    vi.mocked(api.fetchOutline).mockResolvedValue({
      ...TREE,
      chapters: [
        { ...TREE.chapters[0], pages: [{ ...TREE.chapters[0].pages[1], status: 'failed' }] },
      ],
    })
    const { wrapper } = await mountWorkbench()

    expect(findPage(wrapper, '监督与非监督').text()).toContain('失败')
  })
})

describe('大纲可干预（A3）', () => {
  it('停在确认点时，「确认大纲」按钮才亮', async () => {
    const { wrapper } = await mountWorkbench()
    expect(wrapper.find('.wb-confirm').exists()).toBe(false)

    vi.mocked(api.fetchOutline).mockResolvedValue(PAUSED)
    const paused = await mountWorkbench()
    expect(paused.wrapper.find('.wb-confirm').exists()).toBe(true)
  })

  it('删掉一章里的一页再提交：提交的章节树里没有它', async () => {
    vi.mocked(api.fetchOutline).mockResolvedValue(PAUSED)
    const { wrapper } = await mountWorkbench()

    await findPage(wrapper, '线性回归').find('.tree-page__del').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.tree-page').some((row) => row.text().includes('线性回归'))).toBe(false)

    await wrapper.find('.wb-confirm').trigger('click')
    await flushPromises()

    const [, posted] = vi.mocked(api.confirmOutline).mock.calls[0]
    const titles = posted.chapters.flatMap((chapter) => chapter.pages.map((page) => page.title))
    expect(titles).not.toContain('线性回归')
    // 剩下的页原样交回去 —— 封面、测验页这类由服务端按规则补齐的页，
    // 前端照着自己看到的树提交，服务端自己会把它们摘掉再补一遍。
    expect(titles).toContain('监督与非监督')
    expect(titles).toContain('课程导入')
    expect(posted.title).toBe('机器学习入门')
  })

  it('删空了一章就整章不提交（那章没有正文可讲了）', async () => {
    vi.mocked(api.fetchOutline).mockResolvedValue(PAUSED)
    const { wrapper } = await mountWorkbench()

    await findPage(wrapper, '课程导入').find('.tree-page__del').trigger('click')
    await findPage(wrapper, '监督与非监督').find('.tree-page__del').trigger('click')
    await flushPromises()

    await wrapper.find('.wb-confirm').trigger('click')
    await flushPromises()

    const [, posted] = vi.mocked(api.confirmOutline).mock.calls[0]
    expect(posted.chapters.map((chapter) => chapter.no)).toEqual([2])
  })

  it('确认之后刷新大纲（页号是服务端重排的）', async () => {
    vi.mocked(api.fetchOutline).mockResolvedValue(PAUSED)
    const { wrapper } = await mountWorkbench()
    vi.mocked(api.fetchOutline).mockClear()

    await wrapper.find('.wb-confirm').trigger('click')
    await flushPromises()

    expect(api.fetchOutline).toHaveBeenCalledWith('c1')
  })
})

describe('大纲树：折叠、拖序、增删（A3）', () => {
  it('点章标题把这一章折起来，再点展开 —— 折叠只在本地，不打接口', async () => {
    vi.mocked(api.fetchOutline).mockResolvedValue(PAUSED)
    const { wrapper } = await mountWorkbench()
    vi.mocked(api.fetchOutline).mockClear()

    const title = chapterTitle(wrapper, '第二章')
    await title.trigger('click')
    await flushPromises()

    expect(pageTitles(wrapper)).not.toContain('线性回归')
    // 折的是这一章，别的章照旧
    expect(pageTitles(wrapper)).toContain('课程导入')
    expect(api.fetchOutline).not.toHaveBeenCalled()

    await title.trigger('click')
    await flushPromises()
    expect(pageTitles(wrapper)).toContain('线性回归')
  })

  it('拖动一页跨界落到别的位置：屏幕上的顺序变了，提交的也是这个顺序', async () => {
    vi.mocked(api.fetchOutline).mockResolvedValue(PAUSED)
    const { wrapper } = await mountWorkbench()

    expect(pageTitles(wrapper)).toEqual([
      '机器学习入门',
      '课程大纲',
      '课程导入',
      '监督与非监督',
      '线性回归',
      '第二章 · 随堂测验',
      '课程小结',
    ])

    // 把「线性回归」从第二章拖到「课程导入」上面
    await findPage(wrapper, '线性回归').trigger('dragstart')
    await findPage(wrapper, '课程导入').trigger('dragover')
    await findPage(wrapper, '课程导入').trigger('drop')
    await flushPromises()

    expect(pageTitles(wrapper)).toEqual([
      '机器学习入门',
      '课程大纲',
      '线性回归',
      '课程导入',
      '监督与非监督',
      '第二章 · 随堂测验',
      '课程小结',
    ])
    // 改了还没交这件事得写在屏幕上
    expect(wrapper.find('.wb-outline__draft').text()).toContain('未提交')

    await wrapper.find('.wb-confirm').trigger('click')
    await flushPromises()

    const [, posted] = vi.mocked(api.confirmOutline).mock.calls[0]
    // 跨了章就归新的一章：落点在第一章，它就排在第一章里
    expect(posted.chapters[0].pages.map((item) => item.title)).toEqual([
      '线性回归',
      '课程导入',
      '监督与非监督',
    ])
    expect(posted.chapters[1].pages.map((item) => item.title)).toEqual(['第二章 · 随堂测验'])
  })

  it('「+ 页」先在弹窗里问标题，再落到**那一章**末尾', async () => {
    vi.mocked(api.fetchOutline).mockResolvedValue(PAUSED)
    const { wrapper } = await mountWorkbench()

    await chapterTitle(wrapper, '第一章').find('.tree-chapter__add').trigger('click')
    await flushPromises()

    // 加页不该把这一章顺手折起来（按钮上的 .stop 就是为这个）
    expect(pageTitles(wrapper)).toContain('课程导入')

    const dialog = wrapper.findComponent(OutlineAddDialog)
    expect(dialog.props('visible')).toBe(true)
    expect(dialog.props('mode')).toBe('page')
    expect(dialog.props('context')).toContain('第一章')

    dialog.vm.$emit('confirm', { chapterTitle: '', pageTitle: '过拟合与正则化' })
    await flushPromises()

    expect(wrapper.findComponent(OutlineAddDialog).props('visible')).toBe(false)
    expect(pageTitles(wrapper)).toEqual([
      '机器学习入门',
      '课程大纲',
      '课程导入',
      '监督与非监督',
      '过拟合与正则化',
      '线性回归',
      '第二章 · 随堂测验',
      '课程小结',
    ])
  })

  it('「+ 章节」加的章自带一页 —— 空章提交时会被服务端整章丢掉', async () => {
    vi.mocked(api.fetchOutline).mockResolvedValue(PAUSED)
    const { wrapper } = await mountWorkbench()

    await headButton(wrapper, '章节').trigger('click')
    await flushPromises()

    const dialog = wrapper.findComponent(OutlineAddDialog)
    expect(dialog.props('mode')).toBe('chapter')
    expect(dialog.props('chapterCount')).toBe(2)

    dialog.vm.$emit('confirm', { chapterTitle: '第三章 · 神经网络', pageTitle: '反向传播' })
    await flushPromises()

    expect(chapterTitle(wrapper, '第三章')).toBeTruthy()
    expect(findPage(wrapper, '反向传播')).toBeTruthy()

    await wrapper.find('.wb-confirm').trigger('click')
    await flushPromises()

    const [, posted] = vi.mocked(api.confirmOutline).mock.calls[0]
    const last = posted.chapters[posted.chapters.length - 1]
    expect(last.title).toBe('第三章 · 神经网络')
    expect(last.pages.map((item) => item.title)).toEqual(['反向传播'])
  })

  it('不在确认点上时只给读：删不了、拖不动、加不了页', async () => {
    // 默认这棵树是 running / confirmable: false —— 这时候的编辑无处提交
    const { wrapper } = await mountWorkbench()

    expect(wrapper.find('.tree-page__del').exists()).toBe(false)
    expect(wrapper.find('.tree-chapter__add').exists()).toBe(false)
    expect(wrapper.find('.tree-page[draggable="true"]').exists()).toBe(false)
    // 「+ 章节」留着（顺带让人看见这一栏是干嘛的），但是灰的
    expect(headButton(wrapper, '章节').attributes('disabled')).toBeDefined()
  })

  it('点「还原」丢掉本地改动，回到服务端那一版', async () => {
    vi.mocked(api.fetchOutline).mockResolvedValue(PAUSED)
    const { wrapper } = await mountWorkbench()

    await findPage(wrapper, '线性回归').find('.tree-page__del').trigger('click')
    await flushPromises()
    expect(pageTitles(wrapper)).not.toContain('线性回归')
    expect(wrapper.find('.wb-outline__draft').exists()).toBe(true)

    await wrapper.find('.wb-outline__draft .t-button').trigger('click')
    await flushPromises()

    expect(api.fetchOutline).toHaveBeenCalledWith('c1')
    expect(pageTitles(wrapper)).toContain('线性回归')
    expect(wrapper.find('.wb-outline__draft').exists()).toBe(false)
  })
})

describe('页面编辑（A11）', () => {
  it('点一页就把那一页读出来，预览显示服务端的内容', async () => {
    const { wrapper } = await mountWorkbench()

    await findPage(wrapper, '课程导入').trigger('click')
    await flushPromises()

    expect(api.fetchPage).toHaveBeenCalledWith('c1', 3)
    expect(wrapper.find('.page-slide').text()).toContain('身边的机器学习')
    expect(wrapper.find('.page-slide').text()).toContain('从垃圾邮件过滤说起')
  })

  it('图示类型显示的是中文（模型写的 diagram 不该原样出现在幻灯片上）', async () => {
    const { wrapper } = await mountWorkbench()
    await findPage(wrapper, '课程导入').trigger('click')
    await flushPromises()

    const visual = wrapper.find('.slide-visual')
    expect(visual.text()).toContain('示意图')
    expect(visual.text()).not.toContain('diagram')
    expect(visual.text()).toContain('一封被标记的邮件')
  })

  it('模型换了个没见过的图示词，原样显示而不是空一块', async () => {
    // `visual.type` 是自由文本，前端不能拿白名单去卡它
    vi.mocked(api.fetchPage).mockResolvedValue({
      ...PAGE,
      dsl: { ...PAGE.dsl, visual: { type: 'sketchnote', desc: '随手画的笔记' } },
    })
    const { wrapper } = await mountWorkbench()
    await findPage(wrapper, '课程导入').trigger('click')
    await flushPromises()

    expect(wrapper.find('.slide-visual').text()).toContain('sketchnote')
    expect(wrapper.find('.slide-visual').text()).toContain('随手画的笔记')
  })

  it('改讲稿保存：只提交改过的那一项，不把整页推回去', async () => {
    const { wrapper } = await mountWorkbench()
    await findPage(wrapper, '课程导入').trigger('click')
    await flushPromises()

    await wrapper.find('.page-narration textarea').setValue('换个说法，从推荐系统说起。')
    await wrapper.find('.wb-save').trigger('click')
    await flushPromises()

    const [, , patch] = vi.mocked(api.savePage).mock.calls[0]
    expect(patch).toEqual({ narration: [{ text: '换个说法，从推荐系统说起。' }] })
  })

  it('没改过就点保存，不产生一次空提交（空提交会把 rev 白白推上去）', async () => {
    const { wrapper } = await mountWorkbench()
    await findPage(wrapper, '课程导入').trigger('click')
    await flushPromises()

    await wrapper.find('.wb-save').trigger('click')
    await flushPromises()

    expect(api.savePage).not.toHaveBeenCalled()
  })

  it('版本号显示的是服务端那份', async () => {
    const { wrapper } = await mountWorkbench()
    await findPage(wrapper, '课程导入').trigger('click')
    await flushPromises()

    expect(wrapper.find('.page-rev').text()).toContain('rev 1')
  })
})

describe('单页重写（A7）', () => {
  it('点「AI 重写此页」出现指令框，三个快捷指令点一下就是它', async () => {
    const { wrapper } = await mountWorkbench()
    await findPage(wrapper, '课程导入').trigger('click')
    await flushPromises()

    await wrapper.find('.wb-rewrite').trigger('click')
    expect(wrapper.find('.rewrite-panel').exists()).toBe(true)

    const chip = wrapper.findAll('.rewrite-chip').find((node) => node.text() === '更通俗')
    await chip?.trigger('click')
    await wrapper.find('.rewrite-go').trigger('click')
    await flushPromises()

    expect(api.rewritePage).toHaveBeenCalledWith('c1', 3, '更通俗')
  })

  it('重写完显示新的版本号与新的讲稿', async () => {
    vi.mocked(api.rewritePage).mockResolvedValue({
      page: { ...PAGE, rev: 2, dsl: { ...PAGE.dsl, narration: [{ text: '更通俗的一段话。' }] } },
      tokens: 100,
      model: 'stub',
    })
    const { wrapper } = await mountWorkbench()
    await findPage(wrapper, '课程导入').trigger('click')
    await flushPromises()

    await wrapper.find('.wb-rewrite').trigger('click')
    await wrapper.find('.rewrite-go').trigger('click')
    await flushPromises()

    expect(wrapper.find('.page-rev').text()).toContain('rev 2')
    expect(wrapper.find('.page-slide').text()).toContain('更通俗的一段话。')
  })
})

describe('失败与重试（A8）', () => {
  it('某步失败时显示原因与重试按钮，点重试打的是那一步', async () => {
    const { wrapper } = await mountWorkbench()

    FakeEventSource.instances[0].emit('step.failed', {
      stepId: 's3',
      type: 'write',
      error: '上游超时',
      progress: 40,
    })
    await flushPromises()

    const step = wrapper.findAll('.task-step')[2]
    expect(step.classes()).toContain('is-failed')
    expect(step.text()).toContain('上游超时')

    await step.find('.st-retry').trigger('click')
    await flushPromises()

    expect(api.retryStep).toHaveBeenCalledWith('j1', 's3')
  })
})

describe('取消（A9）', () => {
  it('点取消打的是取消接口，然后按服务端说的收尾', async () => {
    const { wrapper } = await mountWorkbench()

    await wrapper.find('.wb-cancel').trigger('click')
    await flushPromises()

    expect(api.cancelJob).toHaveBeenCalledWith('j1')
    expect(wrapper.text()).toContain('已取消')
  })

  it('任务已经结束时不再显示取消按钮', async () => {
    vi.mocked(api.fetchJob).mockResolvedValue({ ...JOB, status: 'done', progress: 100 })
    const { wrapper } = await mountWorkbench()

    expect(wrapper.find('.wb-cancel').exists()).toBe(false)
  })
})
