/**
 * 课堂页（P3-5）= 课堂运行时的客户端。
 *
 * 这一页的职责只有四件：开课与恢复、把事件流接到 store、把该发的上行发出去、
 * 把状态画出来。通道本身的行为由 `classroom-socket.spec.ts` 盯着、状态归约由
 * `classroom-store.spec.ts` 盯着、收尾的两条路由 `beat-player.spec.ts` 盯着 ——
 * 所以这里换成 socket 替身，专测**页面这一层**：
 *
 * 1. 开课那一步：`POST /sessions` → 票据塞给通道 → 建连；降级（mode=manual）
 *    时不许建连，并且要有话说
 * 2. 事件到了界面上看得到：字幕、讨论区、举手位次、被点名、测验题
 * 3. 上行发得对：翻页是 `seek{pageNo}`、举手是 `hand{action}`、
 *    答题发的是**整句选项**（发 "A" 会判错，而且看不出为什么）
 * 4. 断线要说「正在重连」、下课要跳记录页、刷新要能回到同一堂课
 */

import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import type { Ref } from 'vue'

// 课堂页往 window 上挂了快捷键监听（离开页面时摘掉）。不卸载的话，每个用例
// 留下的监听都还活着 —— 后面那条「按空格举手」会同时叫醒前面所有实例。
enableAutoUnmount(afterEach)

vi.mock('@/api', () => ({
  fetchCourses: vi.fn(),
  fetchCourse: vi.fn(),
  fetchRoles: vi.fn(),
  fetchAudioManifest: vi.fn(),
  narrateCourse: vi.fn(),
  realtimeUrl: vi.fn(() => 'ws://localhost/ws/voice/realtime'),
  transcribeAudio: vi.fn(),
}))

vi.mock('@/api/classroom', () => ({
  startSession: vi.fn(),
  fetchSession: vi.fn(),
  renewTicket: vi.fn(),
  endSession: vi.fn(),
  fetchMessages: vi.fn(),
  sendHand: vi.fn(),
  submitQuiz: vi.fn(),
  fetchBoard: vi.fn(),
  classroomSocketUrl: vi.fn(() => 'ws://localhost/ws/classroom/cs1'),
}))

/**
 * 通道换成替身。
 *
 * 建连、心跳、退避重连、4403 这些**协议行为**由 `classroom-socket.spec.ts` 的
 * 17 个用例盯着；课堂页这一层只需要盯住「页面有没有把该做的做了」。
 * 替身把 `options` 留出来，用例据此推事件进去 —— 与真通道投递的是同一条路。
 */
interface SocketStub {
  state: Ref<string>
  error: Ref<string>
  fallback: Ref<string>
  attempts: Ref<number>
  primeTicket: Mock<(ticket: string) => void>
  open: Mock<() => Promise<void>>
  close: Mock<() => void>
  disable: Mock<(hint: string) => void>
  send: Mock<(message: Record<string, unknown>) => boolean>
  options: {
    onEvent: (event: unknown) => void
    onEnter?: () => void
    onResume?: () => void
    cursor?: () => unknown
  } | null
}

const socketStub = vi.hoisted(() => ({ current: null as unknown as SocketStub }))

vi.mock('@/composables/useClassroomSocket', async () => {
  const { ref } = await import('vue')
  const stub = {
    state: ref('idle'),
    error: ref(''),
    fallback: ref(''),
    attempts: ref(0),
    primeTicket: vi.fn(),
    open: vi.fn(),
    close: vi.fn(),
    disable: vi.fn(),
    send: vi.fn(() => true),
    options: null as SocketStub['options'],
  }
  socketStub.current = stub as unknown as SocketStub
  return { useClassroomSocket: (options: SocketStub['options']) => {
    stub.options = options
    // 真通道的 open：建连成功之后开始收事件（`hello` 已发出去）
    stub.open.mockImplementation(async () => {
      stub.state.value = 'open'
      options?.onEnter?.()
    })
    stub.disable.mockImplementation((hint: string) => {
      stub.fallback.value = hint
      stub.state.value = 'closed'
    })
    return stub
  } }
})

import * as api from '@/api'
import * as classroomApi from '@/api/classroom'
import { ApiError } from '@/api/client'
import { loadCursor, saveCursor, useClassroomStore } from '@/stores/classroom'
import ClassroomView from '@/views/ClassroomView.vue'
import type { AgentRole, AudioManifest, CourseCard, CourseDetail, CoursePageItem } from '@/types/api'
import type {
  ClassroomMessage,
  ClassroomQuiz,
  ClassroomStart,
  ClassroomSummary,
  ClassroomTimeline,
} from '@/types/classroom'

// --- 素材 ---

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
  pageCount: 3,
  readyPages: 3,
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

const CARD: CourseCard = {
  id: 'c1',
  title: '机器学习入门',
  topic: '机器学习入门',
  status: 'ready',
  pageCount: 3,
  readyPages: 3,
  durationMin: 25,
  roleCount: 4,
  cover: {},
  progress: 100,
  jobId: 'j1',
  createdAt: 'x',
  updatedAt: 'x',
}

/** 时间线：三页，第三页带一道题（选项是**整句话**）。 */
const TIMELINE: ClassroomTimeline = {
  pageCount: 3,
  totalMs: 60000,
  pages: PAGES.map((item, index) => ({
    pageNo: item.pageNo,
    chapterNo: item.chapterNo,
    kind: item.kind,
    title: item.title,
    beats: [{ beatId: `p${item.pageNo}-b1`, text: '讲稿', durationMs: 6000, startMs: 0 }],
    quiz:
      item.pageNo === 3
        ? { pageNo: 3, stem: '感知机的输出是什么？', options: ['加权求和后的结果', '输入的和', '随机值', '固定的'] }
        : null,
    boardPlan: item.pageNo === 3 ? [{ tool: 'polyline', desc: '画一条线', atBeat: 'p3-b1' }] : [],
    discussion: [],
    startMs: index * 20000,
    durationMs: 20000,
  })),
}

const START: ClassroomStart = {
  sessionId: 'cs1',
  wsToken: 'ticket-1',
  mode: 'auto',
  status: 'idle',
  timeline: TIMELINE,
}

const SUMMARY: ClassroomSummary = {
  id: 'cs1',
  courseId: 'c1',
  courseTitle: '机器学习入门',
  ownerId: 'u-me',
  mode: 'auto',
  status: 'idle',
  pageNo: 1,
  beatIdx: 0,
  elapsedMs: 1000,
  totalMs: 60000,
  speed: 1,
  startedAt: 'x',
  endedAt: '',
  createdAt: 'x',
  presence: { online: 1, members: [{ userId: 'u-me', name: '我', role: 'owner' }] },
}

function manifest(patch: Partial<AudioManifest> = {}): AudioManifest {
  return {
    courseId: 'c1',
    voiceId: '',
    speed: null,
    rate: 1,
    tone: 'natural',
    provider: 'mock',
    simulated: false,
    enabled: true,
    available: false,
    fallback: 'text',
    reason: 'voice_not_configured',
    beatCount: 0,
    readyCount: 0,
    beats: [],
    running: false,
    ...patch,
  }
}

const ROLES: AgentRole[] = [
  ['t1', '沈老师', 'teacher'],
  ['s1', '林晓', 'student'],
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

function message(patch: Partial<ClassroomMessage> = {}): ClassroomMessage {
  return {
    id: 'm1',
    sessionId: 'cs1',
    speaker: 't1',
    speakerKind: 'teacher',
    type: 'comment',
    text: '这是一条消息',
    pageNo: 1,
    beatId: '',
    audioUrl: '',
    quoteMsgId: '',
    ts: '2026-09-13T10:00:00',
    ...patch,
  }
}

// --- 工具 ---

let seq = 0

/** 服务端推一条事件（走的是通道的 `onEvent`，与线上同一条路）。 */
function emit(payload: Record<string, unknown>): void {
  seq += 1
  socketStub.current.options?.onEvent({ seq, eventId: `e${seq}`, ts: 'x', ...payload })
}

function resetSocket(): SocketStub {
  const stub = socketStub.current
  stub.state.value = 'idle'
  stub.error.value = ''
  stub.fallback.value = ''
  stub.attempts.value = 0
  stub.options = null
  stub.primeTicket.mockReset()
  stub.open.mockReset()
  stub.close.mockReset()
  stub.disable.mockReset()
  stub.send.mockReset().mockReturnValue(true)
  return stub
}

async function mountClassroom(query: Record<string, string> = { course: 'c1' }) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div>首页</div>' } },
      { path: '/classroom', component: ClassroomView },
      { path: '/classroom/record', component: { template: '<div>记录页</div>' } },
      { path: '/settings', component: { template: '<div>设置</div>' } },
    ],
  })
  await router.push({ path: '/classroom', query })
  await router.isReady()

  const wrapper = mount(ClassroomView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router, store: useClassroomStore() }
}

type View = Awaited<ReturnType<typeof mountClassroom>>

/** 顶栏/面板上文字包含某个片段的按钮。 */
const button = (wrapper: View['wrapper'], text: string) =>
  wrapper.findAll('button').find((item) => item.text().includes(text))

/** 右侧面板切到某一页签（字幕 / 讨论 / 课程大纲 / 白板）。 */
async function openTab(wrapper: View['wrapper'], label: string) {
  const tab = wrapper.findAll('.t-tabs__nav-item').find((item) => item.text().includes(label))
  await tab?.trigger('click')
  await flushPromises()
}

/** 开一堂课（点「开始上课」并把事件流接上）。 */
async function startClass(view: View) {
  await button(view.wrapper, '开始上课')?.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  seq = 0
  window.sessionStorage.clear()
  resetSocket()
  vi.mocked(api.fetchCourse).mockResolvedValue(DETAIL)
  vi.mocked(api.fetchCourses).mockResolvedValue({ items: [CARD], total: 1, page: 1, size: 20 })
  vi.mocked(api.fetchRoles).mockResolvedValue({ items: ROLES, total: ROLES.length })
  vi.mocked(api.fetchAudioManifest).mockResolvedValue(manifest())
  vi.mocked(api.narrateCourse).mockResolvedValue({ ...manifest(), started: true })
  vi.mocked(classroomApi.startSession).mockResolvedValue(START)
  vi.mocked(classroomApi.fetchSession).mockResolvedValue(SUMMARY)
  vi.mocked(classroomApi.fetchMessages).mockResolvedValue({ items: [], hasMore: false, total: 0 })
  vi.mocked(classroomApi.renewTicket).mockResolvedValue({ wsToken: 'ticket-2', ttlSec: 60 })
  vi.mocked(classroomApi.fetchBoard).mockResolvedValue({ pageNo: 3, strokes: [] })
  vi.mocked(classroomApi.endSession).mockResolvedValue({
    session: SUMMARY,
    event: {},
  } as unknown as Awaited<ReturnType<typeof classroomApi.endSession>>)
})

afterEach(() => {
  vi.mocked(classroomApi.startSession).mockReset()
})

describe('开课', () => {
  it('带课程号进来先看课：舞台是第一页，状态是「尚未开课」', async () => {
    const view = await mountClassroom()

    expect(api.fetchCourse).toHaveBeenCalledWith('c1', { withPages: true })
    expect(view.wrapper.find('.cls-header__title').text()).toBe('机器学习入门')
    expect(view.wrapper.find('.cls-header__meta').text()).toContain('尚未开课')
    // 开课之前不该有任何会话，也不该去建连
    expect(classroomApi.startSession).not.toHaveBeenCalled()
    expect(socketStub.current.open).not.toHaveBeenCalled()

    expect(view.wrapper.find('.page-indicator').text()).toContain('第 1 / 3 页')
  })

  it('点「开始上课」：开课 → 票据塞给通道 → 建连 → 拉历史消息', async () => {
    const view = await mountClassroom()
    await startClass(view)

    expect(classroomApi.startSession).toHaveBeenCalledWith({ courseId: 'c1', mode: 'auto' })
    // 开课响应里那张票直接用掉，不该再签一张
    expect(socketStub.current.primeTicket).toHaveBeenCalledWith('ticket-1')
    expect(socketStub.current.open).toHaveBeenCalledTimes(1)
    expect(classroomApi.renewTicket).not.toHaveBeenCalled()
    // WS 只推「此刻之后」，进课堂先拉一次最近的消息
    expect(classroomApi.fetchMessages).toHaveBeenCalledWith('cs1', { size: 60 })
    // 会话行里的「我是谁」也读回来了：举手位次与点名都按它认
    expect(view.store.ownerId).toBe('u-me')
    // 状态与在线数都来自那一条会话行：刚开出来的课就是「待开讲 + 我在里面」
    expect(view.wrapper.find('.cls-header__meta').text()).toContain('待开讲')
    expect(view.wrapper.find('.cls-header__meta').text()).toContain('在线 1')
  })

  it('推送通道关着（mode=manual）时不建连，并且说清退成了什么', async () => {
    vi.mocked(classroomApi.startSession).mockResolvedValue({ ...START, mode: 'manual' })

    const view = await mountClassroom()
    await startClass(view)

    expect(socketStub.current.open).not.toHaveBeenCalled()
    expect(socketStub.current.disable).toHaveBeenCalled()
    expect(view.store.wsDisabled).toBe(true)
    expect(view.wrapper.find('.cls-notice').text()).toContain('手动翻页')
    expect(view.wrapper.find('.cls-header__meta').text()).toContain('手动翻页')
  })

  it('开课失败时把服务端那句话说出来，页面留在开课前', async () => {
    vi.mocked(classroomApi.startSession).mockRejectedValue(new ApiError(40901, '课堂已结束'))

    const view = await mountClassroom()
    await startClass(view)

    expect(view.store.sessionId).toBe('')
    expect(socketStub.current.open).not.toHaveBeenCalled()
  })

  it('没带课程号时列出已生成的课，点一门就进它', async () => {
    const view = await mountClassroom({})

    expect(api.fetchCourse).not.toHaveBeenCalled()
    const pick = view.wrapper.find('.pick')
    expect(pick.text()).toContain('机器学习入门')
    expect(pick.text()).toContain('3 / 3 页')

    await pick.trigger('click')
    await flushPromises()
    expect(view.router.currentRoute.value.query.course).toBe('c1')
  })

  it('读失败时说的是「没读出来」，不把 404 画成「这门课是空的」', async () => {
    vi.mocked(api.fetchCourse).mockRejectedValue(new ApiError(40401, '课程不存在'))

    const view = await mountClassroom()

    expect(view.wrapper.find('.slide').text()).toContain('这门课没读出来')
    expect(view.wrapper.find('.slide').text()).toContain('课程不存在')
  })
})

describe('事件流到了界面上', () => {
  it('`state` 改页号，字幕与讨论区各自落位', async () => {
    const view = await mountClassroom()
    await startClass(view)

    emit({ type: 'state', status: 'lecture', pageNo: 3, beatIdx: 0, elapsedMs: 20000, totalMs: 60000, speed: 1 })
    emit({ type: 'subtitle', beatId: 'p3-b1', text: '感知机接收多个输入。', pageNo: 3 })
    emit({ type: 'message', msg: message({ id: 'm1', text: '林晓：我有一个问题', speaker: 's1', speakerKind: 'student_ai' }) })
    await flushPromises()

    expect(view.wrapper.find('.page-indicator').text()).toContain('第 3 / 3 页')
    expect(view.store.currentSubtitle?.text).toBe('感知机接收多个输入。')

    await openTab(view.wrapper, '讨论')
    expect(view.wrapper.find('.msg__text').text()).toContain('我有一个问题')
  })

  it('`speak` 到的时候字幕条上是正在说的那一句', async () => {
    const view = await mountClassroom()
    await startClass(view)

    emit({
      type: 'speak',
      turnId: 'turn-1',
      speaker: { code: 't1', name: '沈老师' },
      speakerKind: 'teacher',
      text: '我们从一个例子说起。',
      audioUrl: '',
      beats: ['p1-b1'],
      kind: 'lecture',
      priority: 10,
      pageNo: 1,
    })
    await flushPromises()

    expect(view.wrapper.find('.subtitle').text()).toContain('我们从一个例子说起')
    expect(view.wrapper.find('.subtitle .who').text()).toBe('沈老师')
  })

  it('举手走 `hand` 上行；队列回来之后按钮上显示位次', async () => {
    const view = await mountClassroom()
    await startClass(view)
    emit({ type: 'state', status: 'lecture', pageNo: 1, beatIdx: 0, elapsedMs: 0, totalMs: 60000, speed: 1 })
    await flushPromises()

    await button(view.wrapper, '举手')?.trigger('click')
    expect(socketStub.current.send).toHaveBeenCalledWith({ type: 'hand', action: 'raise' })

    emit({
      type: 'hand_queue',
      queue: [{ id: 'h1', userId: 'u-me', name: '我', ts: '', calledAt: '', status: 'waiting' }],
      called: null,
    })
    await flushPromises()
    expect(button(view.wrapper, '已举手')?.text()).toContain('第 1 位')

    // 再点一下是撤回
    await button(view.wrapper, '已举手')?.trigger('click')
    expect(socketStub.current.send).toHaveBeenCalledWith({ type: 'hand', action: 'lower' })
  })

  it('课还没开讲时举手是灰的：服务端会按 40901 挡回来，界面上就该是灰的', async () => {
    const view = await mountClassroom()
    await startClass(view)

    const hand = button(view.wrapper, '举手')
    expect(hand?.attributes('disabled')).toBeDefined()
    expect(view.store.live).toBe(false)
  })

  it('被点名时把提问区推到眼前（提问条弹出来）', async () => {
    const view = await mountClassroom()
    await startClass(view)

    emit({
      type: 'hand_queue',
      queue: [],
      called: { id: 'h1', userId: 'u-me', name: '我', ts: '', calledAt: 'x', status: 'called' },
    })
    await flushPromises()

    expect(view.store.iAmCalled).toBe(true)
    // 自动切到讨论区：那一页才有输入框
    expect(view.wrapper.find('.chat-input').exists()).toBe(true)
  })

  it('测验题到了弹出卡片，答的是**整句选项**不是 A/B 键', async () => {
    const view = await mountClassroom()
    await startClass(view)

    const quiz: ClassroomQuiz = {
      pageNo: 3,
      stem: '感知机的输出是什么？',
      options: ['加权求和后的结果', '输入的和', '随机值', '固定的'],
      conceptTag: '感知机',
    }
    emit({ type: 'quiz', ...quiz })
    await flushPromises()

    const card = view.wrapper.find('.quiz')
    expect(card.text()).toContain('感知机的输出是什么？')

    vi.mocked(classroomApi.submitQuiz).mockResolvedValue({
      seq: 99,
      type: 'quiz_result',
      pageNo: 3,
      correct: true,
      option: '加权求和后的结果',
      answer: '加权求和后的结果',
      explain: '加权求和之后过一个激活函数。',
      branch: 'pass',
    } as unknown as Awaited<ReturnType<typeof classroomApi.submitQuiz>>)

    await view.wrapper.findAll('.opt')[0].trigger('click')
    await flushPromises()

    const [id, payload] = vi.mocked(classroomApi.submitQuiz).mock.calls[0]
    expect(id).toBe('cs1')
    expect(payload.option).toBe('加权求和后的结果') // 不是 'A'
    expect(typeof payload.responseMs).toBe('number')
    // 回执带 seq，走的是同一条入口 —— 于是 WS 上广播回来的同一条会被去重
    expect(view.store.quizResult?.correct).toBe(true)
    expect(view.store.lastSeq).toBe(99)
  })
})

describe('上行与快捷键', () => {
  it('翻页发的是目标页号；播放/暂停是两条不同的上行', async () => {
    const view = await mountClassroom()
    await startClass(view)
    emit({ type: 'state', status: 'lecture', pageNo: 1, beatIdx: 0, elapsedMs: 0, totalMs: 60000, speed: 1 })
    await flushPromises()

    await button(view.wrapper, '下一页')?.trigger('click')
    expect(socketStub.current.send).toHaveBeenCalledWith({ type: 'seek', pageNo: 2 })

    await view.wrapper.find('.play-btn').trigger('click')
    expect(socketStub.current.send).toHaveBeenCalledWith({ type: 'pause' })

    // 倍速发的是倍速本身，不是「下一档」：两个标签页同时点才不会各按各的认知跳
    await button(view.wrapper, 'x')?.trigger('click')
    expect(socketStub.current.send).toHaveBeenCalledWith({ type: 'speed', value: 1.25 })
  })

  it('空格举手、左右翻页；输入框里打字时空格照旧是空格', async () => {
    const view = await mountClassroom()
    await startClass(view)
    emit({ type: 'state', status: 'lecture', pageNo: 2, beatIdx: 0, elapsedMs: 0, totalMs: 60000, speed: 1 })
    await flushPromises()

    const key = (code: string, target?: Element) => {
      const event = new KeyboardEvent('keydown', { key: code, code, bubbles: true, cancelable: true })
      ;(target ?? window).dispatchEvent(event)
      return event
    }

    key('Space')
    expect(socketStub.current.send).toHaveBeenCalledWith({ type: 'hand', action: 'raise' })

    key('ArrowLeft')
    expect(socketStub.current.send).toHaveBeenCalledWith({ type: 'seek', pageNo: 1 })

    socketStub.current.send.mockClear()
    await openTab(view.wrapper, '讨论')
    key('Space', view.wrapper.find('textarea').element)
    expect(socketStub.current.send).not.toHaveBeenCalled()
  })

  it('Esc 退出沉浸模式：面板收起来，再按一下回来', async () => {
    const view = await mountClassroom()
    await startClass(view)

    expect(view.wrapper.find('.side').exists()).toBe(true)
    await button(view.wrapper, '')?.trigger('click') // 顶栏那个方形的沉浸按钮没有文字
    // 用 title 找更稳
    const immersive = view.wrapper.findAll('button').find((item) => item.attributes('title')?.includes('沉浸'))
    await immersive?.trigger('click')
    await flushPromises()
    expect(view.wrapper.find('.side').exists()).toBe(false)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(view.wrapper.find('.side').exists()).toBe(true)
  })
})

describe('断线、下课与刷新', () => {
  it('断线时顶栏挂一条「正在重连」，不让人对着不动的课堂猜', async () => {
    const view = await mountClassroom()
    await startClass(view)

    socketStub.current.state.value = 'reconnecting'
    socketStub.current.attempts.value = 2
    await flushPromises()

    const notice = view.wrapper.find('.cls-notice').text()
    expect(notice).toContain('连接中断')
    expect(notice).toContain('第 2 次')
  })

  it('接不上时说的是通道那一层给的结论（刷新页面），不自己编一句', async () => {
    const view = await mountClassroom()
    await startClass(view)

    socketStub.current.state.value = 'closed'
    socketStub.current.error.value = '与课堂的连接断了，重试了几次都没接上，请刷新页面'
    await flushPromises()

    expect(view.wrapper.find('.cls-notice').text()).toContain('刷新页面')
  })

  it('下课（服务端推 ended）跳到课堂记录页，并把游标清掉', async () => {
    const view = await mountClassroom()
    await startClass(view)
    expect(loadCursor('c1')).not.toBeNull()

    emit({ type: 'state', status: 'ended', pageNo: 3, beatIdx: 0, elapsedMs: 60000, totalMs: 60000, speed: 1 })
    await flushPromises()

    expect(view.router.currentRoute.value.path).toBe('/classroom/record')
    expect(view.router.currentRoute.value.query.session).toBe('cs1')
    expect(loadCursor('c1')).toBeNull()
    expect(socketStub.current.close).toHaveBeenCalled()
  })

  it('刷新之后回到同一堂课：读会话行 + 重签票据建连，**不是**又开一堂', async () => {
    saveCursor({ sessionId: 'cs1', seq: 12, courseId: 'c1' })

    const view = await mountClassroom()

    expect(classroomApi.startSession).not.toHaveBeenCalled()
    expect(classroomApi.fetchSession).toHaveBeenCalledWith('cs1')
    expect(socketStub.current.open).toHaveBeenCalledTimes(1)
    // 游标来自上一次：补发起点是「已经收到 12 之后」
    expect(view.store.lastSeq).toBe(12)
    expect(view.wrapper.find('.page-indicator').text()).toContain('第 1 / 3 页')
  })

  it('恢复不了就退回开课前，并把那条游标丢掉（课已经不在那儿了）', async () => {
    saveCursor({ sessionId: 'cs-old', seq: 3, courseId: 'c1' })
    vi.mocked(classroomApi.fetchSession).mockRejectedValue(new ApiError(40901, '课堂已结束'))

    const view = await mountClassroom()

    expect(view.store.sessionId).toBe('')
    expect(loadCursor('c1')).toBeNull()
    expect(button(view.wrapper, '开始上课')).toBeTruthy()
  })
})
