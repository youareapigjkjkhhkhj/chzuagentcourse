/**
 * 课堂记录回看页（P3-6）。
 *
 * 这一页的职责只有一件：把 `GET /record` 给的那一份**摊开**。它不建连接、
 * 不发上行、不碰课堂 store —— 所以这里要盯的只有三件事：
 *
 * 1. 读得到：拿到记录就画出来，读不出来要说清是哪一种失败（不是白屏）
 * 2. 摊得对：字幕按页分组、消息默认滤掉讲稿、板书按页、作答一次一行
 * 3. 边界：还在上的课要说明「到此刻」；没有课号不瞎请求
 */

import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

enableAutoUnmount(afterEach)

vi.mock('@/api', () => ({
  fetchRoles: vi.fn(),
}))

vi.mock('@/api/classroom', () => ({
  fetchRecord: vi.fn(),
}))

import * as api from '@/api'
import * as classroomApi from '@/api/classroom'
import { ApiError } from '@/api/client'
import ClassroomRecordView from '@/views/ClassroomRecordView.vue'
import type { AgentRole } from '@/types/api'
import type {
  BoardStroke,
  ClassroomMessage,
  ClassroomRecord,
  RecordSubtitle,
} from '@/types/classroom'

const ROLES: AgentRole[] = [
  {
    id: 'r1',
    code: 'shen',
    name: '沈老师',
    role: 'teacher',
    avatarColor: '#8b5a2b',
    voiceProfileId: 'v1',
    builtin: true,
    persona: { tone: '', style: '', speechRate: 1, pitch: 1, systemHint: '' },
  },
]

function subtitle(beatId: string, pageNo: number, text: string, ts: string): RecordSubtitle {
  return { beatId, pageNo, speaker: 'shen', text, audioUrl: '', ts }
}

function message(patch: Partial<ClassroomMessage> = {}): ClassroomMessage {
  return {
    id: 'm1',
    sessionId: 'cs1',
    speaker: 'shen',
    speakerKind: 'teacher',
    type: 'lecture',
    text: '第一句讲稿。',
    pageNo: 1,
    beatId: '',
    audioUrl: '',
    quoteMsgId: '',
    ts: '2026-09-13T10:00:05',
    ...patch,
  }
}

function stroke(): BoardStroke {
  return {
    id: 's1',
    sessionId: 'cs1',
    pageNo: 2,
    strokeNo: 1,
    tool: 'polyline',
    color: '#0052d9',
    width: 3,
    points: [
      { x: 0.1, y: 0.1 },
      { x: 0.5, y: 0.5 },
    ],
    text: '',
    atBeatId: 'p2-b1',
    durMs: 400,
    author: 'teacher',
  }
}

function record(patch: Partial<ClassroomRecord> = {}): ClassroomRecord {
  return {
    session: {
      id: 'cs1',
      courseId: 'c1',
      ownerId: 'u1',
      mode: 'auto',
      status: 'ended',
      pageNo: 12,
      beatIdx: 3,
      elapsedMs: 1_500_000,
      totalMs: 1_500_000,
      speed: 1,
      startedAt: '2026-09-13T10:00:00',
      endedAt: '2026-09-13T10:25:00',
      createdAt: '2026-09-13T09:59:00',
    },
    courseTitle: '机器学习入门',
    participants: [
      { userId: 'u1', name: '小明', role: 'owner', joinedAt: '2026-09-13T10:00:00', leftAt: '' },
    ],
    subtitles: [
      subtitle('p1-b1', 1, '感知机接收多个输入。', '2026-09-13T10:00:05'),
      subtitle('p1-b2', 1, '它们各自带一个权重。', '2026-09-13T10:00:12'),
      subtitle('p2-b1', 2, '第二页讲的是激活函数。', '2026-09-13T10:02:00'),
    ],
    messages: [
      message({ id: 'm1', text: '第一句讲稿。' }),
      message({ id: 'm2', speaker: 'linxiao', speakerKind: 'student_ai', type: 'question', text: '为什么要有偏置？', pageNo: 1 }),
      message({ id: 'm3', speakerKind: 'me', speaker: 'me', type: 'comment', text: '这里没听懂', pageNo: 2 }),
      message({ id: 'm4', speakerKind: 'system', speaker: 'system', type: 'system', text: '课堂已结束。' }),
    ],
    boards: [{ pageNo: 2, strokes: [stroke()] }],
    quizzes: [
      { pageNo: 9, option: '感知机是一种线性分类器', correct: false, nodeId: 'q1', responseMs: 4200, ts: '2026-09-13T10:10:00' },
      { pageNo: 9, option: '感知机可以表示异或', correct: true, nodeId: 'q1', responseMs: 2600, ts: '2026-09-13T10:10:20' },
    ],
    stats: {
      messages: 4,
      subtitles: 3,
      boardPages: 1,
      strokes: 1,
      quizAttempts: 2,
      quizCorrect: 1,
      durationMs: 1_500_000,
    },
    ...patch,
  }
}

async function mountRecord(query: Record<string, string> = { session: 'cs1' }) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div>首页</div>' } },
      { path: '/classroom', component: { template: '<div>课堂</div>' } },
      { path: '/classroom/record', component: ClassroomRecordView },
    ],
  })
  await router.push({ path: '/classroom/record', query })
  await router.isReady()

  const wrapper = mount(ClassroomRecordView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

type View = Awaited<ReturnType<typeof mountRecord>>

const textOf = (wrapper: View['wrapper']) => wrapper.text()

async function openTab(wrapper: View['wrapper'], label: string) {
  const tab = wrapper.findAll('.t-tabs__nav-item').find((item) => item.text().includes(label))
  await tab?.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  vi.mocked(api.fetchRoles).mockResolvedValue({ items: ROLES, total: ROLES.length })
  vi.mocked(classroomApi.fetchRecord).mockResolvedValue(record())
})

describe('读得到', () => {
  it('课名、状态、统计条一次给全', async () => {
    const view = await mountRecord()

    expect(textOf(view.wrapper)).toContain('机器学习入门')
    expect(textOf(view.wrapper)).toContain('已下课')
    // 25 分钟；字幕/消息/板书/作答四个数
    expect(textOf(view.wrapper)).toContain('25:00')
    expect(textOf(view.wrapper)).toContain('3 句')
    expect(textOf(view.wrapper)).toContain('4 条')
    expect(textOf(view.wrapper)).toContain('1 页 1 笔')
    expect(textOf(view.wrapper)).toContain('2 次 · 对 1')
  })

  it('谁上过这堂课：名字来自记录，不是用户号', async () => {
    const view = await mountRecord()

    const people = view.wrapper.findAll('.person').map((item) => item.text())
    expect(people[0]).toContain('小明')
    expect(people[0]).toContain('开课的人')
  })

  it('没有课号就不请求，也不装成读到了', async () => {
    const view = await mountRecord({})

    expect(classroomApi.fetchRecord).not.toHaveBeenCalled()
    expect(textOf(view.wrapper)).toContain('没有指定要回看的课堂')
  })

  it('读不出来说清是哪一种（404 = 不是我的课），并给一条重试', async () => {
    vi.mocked(classroomApi.fetchRecord).mockRejectedValue(
      new ApiError(40400, '这堂课不存在，或者不是你的课'),
    )
    const view = await mountRecord()

    expect(textOf(view.wrapper)).toContain('这份课堂记录读不出来')
    expect(textOf(view.wrapper)).toContain('这堂课不存在，或者不是你的课')
  })

  it('还在上的课说明「到此刻」，不假装这是最终结果', async () => {
    vi.mocked(classroomApi.fetchRecord).mockResolvedValue(
      record({ session: { ...record().session, status: 'lecture', endedAt: '', elapsedMs: 60_000 } }),
    )
    const view = await mountRecord()

    expect(textOf(view.wrapper)).toContain('这堂课还在上')
    expect(textOf(view.wrapper)).toContain('到此刻为止的记录')
    expect(textOf(view.wrapper)).toContain('讲解中')
  })
})

describe('摊得对', () => {
  it('字幕按页分段：同一页合成一段，翻页另起一段', async () => {
    const view = await mountRecord()

    const blocks = view.wrapper.findAll('.page-block')
    expect(blocks).toHaveLength(2)
    expect(blocks[0].text()).toContain('第 1 页')
    expect(blocks[0].text()).toContain('2 句')
    expect(blocks[0].text()).toContain('感知机接收多个输入。')
    expect(blocks[1].text()).toContain('第 2 页')
    expect(blocks[1].text()).toContain('第二页讲的是激活函数。')
    // 说话人取角色库里的名字，不是 code
    expect(blocks[0].text()).toContain('沈老师')
  })

  it('消息默认只看互动：讲解有单独一栏，不在这里再淹一遍', async () => {
    const view = await mountRecord()
    await openTab(view.wrapper, '消息记录')

    const texts = view.wrapper.findAll('.msg__text').map((item) => item.text())
    expect(texts).toEqual(['为什么要有偏置？', '这里没听懂'])
    expect(textOf(view.wrapper)).toContain('课堂已结束。') // 系统提示照样在
  })

  it('勾上「连讲解一起显示」就能看到全部', async () => {
    const view = await mountRecord()
    await openTab(view.wrapper, '消息记录')

    const box = view.wrapper.find('.rec-toolbar input[type="checkbox"]')
    await box.setValue(true)
    await flushPromises()

    const texts = view.wrapper.findAll('.msg__text').map((item) => item.text())
    expect(texts).toContain('第一句讲稿。')
    expect(texts).toHaveLength(3)
  })

  it('板书按页给一张快照，画的是这一页的笔画', async () => {
    const view = await mountRecord()
    await openTab(view.wrapper, '板书快照')

    const block = view.wrapper.find('.board-block')
    expect(block.text()).toContain('第 2 页')
    expect(block.text()).toContain('1 笔')
    // 归一化坐标乘画布尺寸：0.1 → 100、0.5 → 500（逻辑画布 1000×562）
    expect(block.find('polyline').attributes('points')).toBe('100,56.2 500,281')
  })

  it('作答一次一行：答错重答是两行，不合并', async () => {
    const view = await mountRecord()
    await openTab(view.wrapper, '测验作答')

    const attempts = view.wrapper.findAll('.attempt')
    expect(attempts).toHaveLength(2)
    expect(attempts[0].text()).toContain('第 9 页')
    expect(attempts[0].text()).toContain('回答错误')
    expect(attempts[0].text()).toContain('感知机是一种线性分类器')
    expect(attempts[0].text()).toContain('用时 4.2 秒')
    expect(attempts[1].text()).toContain('回答正确')
  })

  it('没有留下东西的那几栏各自给一句话，不是空白', async () => {
    vi.mocked(classroomApi.fetchRecord).mockResolvedValue(
      record({
        subtitles: [],
        messages: [],
        boards: [],
        quizzes: [],
        stats: { messages: 0, subtitles: 0, boardPages: 0, strokes: 0, quizAttempts: 0, quizCorrect: 0, durationMs: 0 },
      }),
    )
    const view = await mountRecord()

    expect(textOf(view.wrapper)).toContain('这堂课没有留下字幕。')
    await openTab(view.wrapper, '消息记录')
    expect(textOf(view.wrapper)).toContain('这堂课没有留下消息。')
    await openTab(view.wrapper, '板书快照')
    expect(textOf(view.wrapper)).toContain('这堂课没有留下板书。')
    await openTab(view.wrapper, '测验作答')
    expect(textOf(view.wrapper)).toContain('这堂课没有作答记录。')
  })
})
