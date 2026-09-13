/**
 * 工作台会话（P4-A9~A12 / F4-10~F4-12）。
 *
 * 这一层是**帧与界面之间的那道缝**：后端的五种帧长什么样已经由
 * `tests/contract/test_p4_workbench_api.py` 钉住了，这里钉的是另一半 ——
 * 前端把它们读成了什么。所以每条用例都从「服务端发了一帧」开始，
 * 断言的是状态（消息、操作卡、回退），不是像素。
 *
 * 三条与 `useGenerationStream` 同一口径的规矩，各自有一条用例：
 * **流里那些字只是它正在出现的样子**（归档以消息列表为准）、
 * **技能在跑的时候就得看得见**（转圈的卡）、
 * **回退是删上下文不是撤销**（服务端那句 `pageNotice` 原样说出来）。
 */

import { effectScope, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  chatStreamUrl: (courseId: string) => `/api/courses/${courseId}/chat/stream`,
  fetchChatMessages: vi.fn(),
  sendChatMessage: vi.fn(),
  rollbackChat: vi.fn(),
  fetchSkills: vi.fn(),
}))

import * as api from '@/api'
import { useWorkbenchChat, type PageRewrite } from '@/composables/useWorkbenchChat'
import type { ChatMessageItem } from '@/types/api'

/** 一个可以手动喂事件的 EventSource 替身（与生成流那份同一个写法）。 */
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

  /** 一帧坏数据：流不该就此断掉。 */
  emitRaw(name: string, raw: string) {
    for (const handler of this.listeners.get(name) ?? []) {
      handler({ data: raw })
    }
  }
}

/** 服务端消息列表里的一条（归档那一份）。 */
function archived(over: Partial<ChatMessageItem> = {}): ChatMessageItem {
  return {
    id: 'm1',
    sessionId: 's1',
    seq: 1,
    role: 'assistant',
    content: '好的，我把第 3 页改口语了一些。',
    skillCalls: [],
    refPageNo: null,
    tokens: 12,
    createdAt: 'x',
    ...over,
  }
}

/** 挂在一个 scope 里跑：`onScopeDispose(close)` 要靠它才生效（同真实组件）。 */
function mountChat(options: { onPageRewritten?: (info: PageRewrite) => void } = {}) {
  const courseId = ref('c1')
  const scope = effectScope()
  const chat = scope.run(() => useWorkbenchChat(courseId, options))!
  return { chat, scope, courseId }
}

const stream = () => FakeEventSource.instances[FakeEventSource.instances.length - 1]

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.mocked(api.fetchChatMessages).mockResolvedValue({
    sessionId: 's1',
    items: [],
    lastSeq: 0,
    running: false,
  })
  vi.mocked(api.fetchSkills).mockResolvedValue({ items: [], maxActions: 4 })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('连上这门课的会话', () => {
  it('换课程就换一条流，旧的关掉 —— 上一门课的字不该出现在这一门里', async () => {
    const { chat, courseId } = mountChat()
    await Promise.resolve()

    expect(stream().url).toContain('/courses/c1/chat/stream')
    expect(api.fetchChatMessages).toHaveBeenCalledWith('c1')

    courseId.value = 'c2'
    await Promise.resolve()

    expect(FakeEventSource.instances[0].closed).toBe(true)
    expect(stream().url).toContain('/courses/c2/chat/stream')
    expect(chat.messages.value).toEqual([])
  })

  it('流里收到的字只是「正在出现的那一条」，一轮结束以消息列表为准', async () => {
    vi.mocked(api.fetchChatMessages).mockResolvedValue({
      sessionId: 's1',
      items: [archived()],
      lastSeq: 1,
      running: false,
    })
    const { chat } = mountChat()
    await Promise.resolve()

    stream().emit('agent.delta', { messageId: 'm1', text: '好的，我' })
    stream().emit('agent.delta', { messageId: 'm1', text: '把第 3 页改口语了一些。' })

    expect(chat.draftId.value).toBe('m1')
    expect(chat.draftText.value).toBe('好的，我把第 3 页改口语了一些。')
    expect(chat.running.value).toBe(false) // 还没结束

    stream().emit('agent.done', { messageId: 'm1', tokens: 12 })
    await Promise.resolve()

    // 归档那一份回来了：打字机停、草稿清、以库里那条为准（它有 tokens）
    expect(chat.draftId.value).toBe('')
    expect(chat.running.value).toBe(false)
    expect(chat.messages.value[0].content).toContain('改口语')
    expect(api.fetchChatMessages).toHaveBeenCalledTimes(2)
  })

  it('技能开跑就出现一张转圈的卡，跑完填成结果', async () => {
    const { chat } = mountChat()
    await Promise.resolve()

    stream().emit('agent.skill', {
      messageId: 'm1',
      skillId: 'k1',
      skill: 'rewrite_page',
      args: { pageNo: 3, instruction: '更口语' },
      why: '用户要求',
    })

    const [card] = chat.liveSkills.value.m1
    expect(card.status).toBe('running')
    expect(card.args.pageNo).toBe(3)
    expect(card.result).toBeNull()

    stream().emit('agent.skill_done', {
      messageId: 'm1',
      skillId: 'k1',
      skill: 'rewrite_page',
      status: 'ok',
      result: { pageNo: 3, rev: 2 },
      durationMs: 820,
    })

    expect(chat.liveSkills.value.m1[0].status).toBe('ok')
    expect(chat.liveSkills.value.m1[0].result?.rev).toBe(2)
    expect(chat.liveSkills.value.m1[0].durationMs).toBe(820)
  })

  it('同一张卡不会因为重复的 agent.skill 帧出现两次，坏帧也不会打断流', async () => {
    const { chat } = mountChat()
    await Promise.resolve()

    stream().emit('agent.skill', { messageId: 'm1', skillId: 'k1', skill: 'add_page' })
    stream().emit('agent.skill', { messageId: 'm1', skillId: 'k1', skill: 'add_page' })
    stream().emitRaw('agent.delta', '{ 这不是 JSON')
    stream().emit('agent.delta', { messageId: 'm1', text: '照常收字' })

    expect(chat.liveSkills.value.m1).toHaveLength(1)
    expect(chat.draftText.value).toBe('照常收字')
  })

  it('页面被改的那一帧连同「删没删」一起交给工作台', async () => {
    const seen: PageRewrite[] = []
    mountChat({ onPageRewritten: (info) => seen.push(info) })
    await Promise.resolve()

    stream().emit('page.rewritten', {
      messageId: 'm1',
      pageNo: 3,
      rev: 2,
      skill: 'rewrite_page',
      sources: [{ materialId: 'f1', chunkId: 'k9', pageNo: 12, quote: '原文' }],
    })
    stream().emit('page.rewritten', { messageId: 'm1', pageNo: 4, removed: true, rev: 0 })

    expect(seen[0]).toMatchObject({ pageNo: 3, removed: false, rev: 2 })
    // 出处用的是 `materialId` —— 与页面 DSL 里那份同一个名字，前端只有一个开抽屉的入口
    expect(seen[0].sources[0].materialId).toBe('f1')
    expect(seen[1]).toMatchObject({ pageNo: 4, removed: true, rev: 0 })
  })
})

describe('发一句话', () => {
  it('发出去先本地回显，从列表里认出这一句之后撤回显', async () => {
    vi.mocked(api.sendChatMessage).mockResolvedValue({
      sessionId: 's1',
      messageId: 'm2',
      userMessageId: 'm1',
      seq: 1,
      stream: '/api/courses/c1/chat/stream',
    })
    // 第一次问是空的（那句还没落库），第二次带上用户那句
    vi.mocked(api.fetchChatMessages)
      .mockResolvedValueOnce({ sessionId: 's1', items: [], lastSeq: 0, running: false })
      .mockResolvedValue({
        sessionId: 's1',
        items: [archived({ id: 'm1', role: 'user', content: '第 3 页口语一点' })],
        lastSeq: 1,
        running: true,
      })

    const { chat } = mountChat()
    await Promise.resolve()

    const sent = await chat.send('第 3 页口语一点', 3)

    expect(sent).toBe(true)
    expect(api.sendChatMessage).toHaveBeenCalledWith('c1', { text: '第 3 页口语一点', refPageNo: 3 })
    expect(chat.draftId.value).toBe('m2') // 字接到这条 assistant 消息上
    expect(chat.pendingUser.value).toBeNull() // 列表里认出来了，本地那条撤掉
    expect(chat.running.value).toBe(true) // 服务端说这一轮在跑
  })

  it('没发出去就如实报错，本地那条回显跟着撤（屏幕上不留一句没发生的话）', async () => {
    vi.mocked(api.sendChatMessage).mockRejectedValue(new Error('连不上'))

    const { chat } = mountChat()
    await Promise.resolve()

    const sent = await chat.send('改一下')

    expect(sent).toBe(false)
    expect(chat.pendingUser.value).toBeNull()
    expect(chat.error.value).toBe('连不上')
    expect(chat.running.value).toBe(false)
  })
})

describe('回退', () => {
  it('回退只说服务端那句「课程内容没跟着回退」，不替它许诺', async () => {
    vi.mocked(api.rollbackChat).mockResolvedValue({
      sessionId: 's1',
      rolledBackTo: 1,
      removed: 3,
      removedMessages: [],
      lastKeptSeq: 4,
      pageNotice: '课程内容没有跟着回退，已改过的页面还在',
    })
    const { chat } = mountChat()
    await Promise.resolve()

    stream().emit('agent.delta', { messageId: 'm9', text: '半句' })
    const notice = await chat.rollback('m5')

    expect(api.rollbackChat).toHaveBeenCalledWith('c1', { messageId: 'm5' })
    expect(notice).toBe('课程内容没有跟着回退，已改过的页面还在')
    // 回退之后那半句不能还挂在屏幕上：它引用的上下文已经没了
    expect(chat.draftId.value).toBe('')
    expect(chat.draftText.value).toBe('')
  })
})
