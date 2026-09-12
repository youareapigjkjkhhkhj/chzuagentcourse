/**
 * 生成进度流（P1-B2 / P1-B5）。
 *
 * 两条规矩贯穿全篇：
 *
 * 1. **前端不许自己造进度**。屏幕上的每一个百分比、每一个「生成中」，
 *    都得能在服务端发来的某一帧里找到出处 —— 所以这里连「没有事件时
 *    进度是多少」都要断言（0，而不是一个会自己往上爬的假进度条）。
 * 2. **断了就如实说断了**。EventSource 自己会重连，重连上不来就用
 *    `GET /api/jobs/{jobId}` 问清楚；两条路都断了，界面显示的是「未连接」，
 *    不是「进度 100%」。
 */

import { effectScope, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  fetchJob: vi.fn(),
  streamUrl: (jobId: string) => `/api/courses/generate/${jobId}/stream`,
}))

import * as api from '@/api'
import { useGenerationStream } from '@/composables/useGenerationStream'

/** 一个可以手动喂事件的 EventSource 替身。 */
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

  /** 服务端发了一帧。 */
  emit(name: string, payload: unknown) {
    for (const handler of this.listeners.get(name) ?? []) {
      handler({ data: JSON.stringify(payload) })
    }
  }

  /** 连接出错（浏览器会自己重连，这里模拟重连也没成）。 */
  fail() {
    this.onerror?.({})
  }

  static reset() {
    FakeEventSource.instances = []
  }

  static get latest(): FakeEventSource {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1]
  }
}

const JOB = {
  id: 'j1',
  courseId: 'c1',
  status: 'running',
  progress: 42,
  totalMs: 0,
  totalTokens: 0,
  options: {},
  error: '',
  createdAt: 'x',
  updatedAt: 'x',
  steps: [
    {
      id: 's1',
      jobId: 'j1',
      seq: 1,
      type: 'parse',
      title: '解析需求与受众画像',
      status: 'done',
      detail: {},
      durationMs: 6000,
      tokens: 100,
      error: '',
      startedAt: 'x',
      finishedAt: 'x',
    },
    {
      id: 's2',
      jobId: 'j1',
      seq: 2,
      type: 'outline',
      title: '生成课程大纲',
      status: 'running',
      detail: { percent: 30 },
      durationMs: 0,
      tokens: 0,
      error: '',
      startedAt: 'x',
      finishedAt: null,
    },
  ],
  currentStep: null,
  failedSteps: [],
  retryable: false,
}

function stream(jobId = 'j1') {
  const scope = effectScope()
  const state = scope.run(() => useGenerationStream(ref(jobId)))!
  return { state, scope }
}

beforeEach(() => {
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.mocked(api.fetchJob).mockResolvedValue(JOB as never)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('事件驱动', () => {
  it('连上的是这条任务自己的流', () => {
    const { state } = stream('j9')

    expect(FakeEventSource.latest.url).toBe('/api/courses/generate/j9/stream')
    expect(state.connected.value).toBe(true)
  })

  it('没有收到任何事件时，进度就是 0、步骤就是空的（不自己造）', () => {
    const { state } = stream()

    expect(state.progress.value).toBe(0)
    expect(state.steps.value).toEqual([])
    expect(state.livePageNo.value).toBe(0)
    expect(state.active.value).toBe(true)
  })

  it('job.start 给出六个步骤，状态全是「待生成」', () => {
    const { state } = stream()

    FakeEventSource.latest.emit('job.start', {
      jobId: 'j1',
      courseId: 'c1',
      steps: [
        { id: 's1', type: 'parse', title: '解析需求与受众画像', weight: 5 },
        { id: 's2', type: 'outline', title: '生成课程大纲', weight: 10 },
      ],
    })

    expect(state.steps.value.map((step) => step.status)).toEqual(['wait', 'wait'])
    expect(state.steps.value[0]).toMatchObject({ id: 's1', title: '解析需求与受众画像' })
    expect(state.progress.value).toBe(0)
  })

  it('step.progress 把「正在写第几页、第几批」带过来', () => {
    const { state } = stream()
    FakeEventSource.latest.emit('job.start', { jobId: 'j1', steps: [{ id: 's3', type: 'write', title: '写页' }] })

    FakeEventSource.latest.emit('step.start', { stepId: 's3', type: 'write', title: '写页', progress: 20 })
    FakeEventSource.latest.emit('step.progress', {
      stepId: 's3',
      type: 'write',
      percent: 50,
      progress: 20,
      detail: {
        pageNo: 7,
        batches: [{ label: '撰写第 1–6 页', from: 1, to: 6, total: 6, done: 6, status: 'done' }],
      },
    })

    expect(state.steps.value[0].status).toBe('running')
    expect(state.progress.value).toBe(20)
    expect(state.livePageNo.value).toBe(7)
    expect(state.batches.value).toHaveLength(1)
    expect(state.steps.value[0].percent).toBe(50)
  })

  it('step.done 之后问一次 REST —— 耗时以库里那份为准，不是前端掐表', async () => {
    const { state } = stream()
    FakeEventSource.latest.emit('job.start', { jobId: 'j1', steps: [{ id: 's1', type: 'parse', title: '解析' }] })

    FakeEventSource.latest.emit('step.done', { stepId: 's1', type: 'parse', tokens: 100, progress: 5 })
    await Promise.resolve()

    expect(api.fetchJob).toHaveBeenCalledWith('j1')
    expect(state.steps.value[0].status).toBe('done')
    expect(state.steps.value[0].durationMs).toBe(6000)
  })

  it('step.failed 带上失败原因', () => {
    const { state } = stream()
    FakeEventSource.latest.emit('job.start', { jobId: 'j1', steps: [{ id: 's3', type: 'write', title: '写页' }] })

    FakeEventSource.latest.emit('step.failed', { stepId: 's3', type: 'write', error: '上游超时', progress: 40 })

    expect(state.steps.value[0]).toMatchObject({ status: 'failed', error: '上游超时' })
    expect(state.active.value).toBe(true)
  })

  it('page.ready 记下已完成的页号', () => {
    const { state } = stream()

    FakeEventSource.latest.emit('page.ready', { pageNo: 7, kind: 'concept', title: '梯度下降' })
    FakeEventSource.latest.emit('page.ready', { pageNo: 8, kind: 'concept', title: '反向传播' })

    expect(state.readyPages.value).toEqual([7, 8])
  })

  it('job.paused 停在大纲确认点：任务没结束，但已经在等用户', () => {
    const { state } = stream()

    FakeEventSource.latest.emit('job.paused', { jobId: 'j1', progress: 15 })

    expect(state.status.value).toBe('paused')
    expect(state.active.value).toBe(true)
    expect(FakeEventSource.latest.closed).toBe(false)
  })

  it.each([
    ['job.done', 'done'],
    ['job.failed', 'failed'],
    ['job.canceled', 'canceled'],
  ])('%s 之后收流（浏览器会自动重连，不收就会一遍遍重放历史）', (event, status) => {
    const { state } = stream()

    FakeEventSource.latest.emit(event, { jobId: 'j1', error: '炸了', progress: 60 })

    expect(state.status.value).toBe(status)
    expect(state.active.value).toBe(false)
    expect(FakeEventSource.latest.closed).toBe(true)
    expect(state.error.value).toBe(status === 'failed' ? '炸了' : '')
  })
})

describe('断了怎么办', () => {
  it('一次断线先不算数：EventSource 自己会重连', () => {
    const { state } = stream()

    FakeEventSource.latest.fail()

    expect(state.connected.value).toBe(false)
    expect(state.mode.value).toBe('stream')
  })

  it('两次都连不上就转去轮询 REST，数字仍来自服务端', async () => {
    vi.useFakeTimers()
    const { state } = stream()

    FakeEventSource.latest.fail()
    FakeEventSource.latest.fail()
    expect(state.mode.value).toBe('polling')

    await vi.advanceTimersByTimeAsync(3000)

    expect(api.fetchJob).toHaveBeenCalled()
    expect(state.progress.value).toBe(42)
    expect(state.steps.value.map((step) => step.status)).toEqual(['done', 'running'])
  })

  it('流回到线上就停掉轮询（同一个数字问两遍没有意义）', async () => {
    vi.useFakeTimers()
    const { state } = stream()
    FakeEventSource.latest.fail()
    FakeEventSource.latest.fail()
    await vi.advanceTimersByTimeAsync(3000)
    vi.mocked(api.fetchJob).mockClear()

    FakeEventSource.latest.emit('step.progress', { stepId: 's2', percent: 80, progress: 60 })
    await vi.advanceTimersByTimeAsync(9000)

    expect(state.mode.value).toBe('stream')
    expect(api.fetchJob).not.toHaveBeenCalled()
    expect(state.progress.value).toBe(60)
  })

  it('轮询拿到的终态同样收流', async () => {
    vi.useFakeTimers()
    vi.mocked(api.fetchJob).mockResolvedValue({ ...JOB, status: 'done', progress: 100 } as never)
    const { state } = stream()
    FakeEventSource.latest.fail()
    FakeEventSource.latest.fail()

    await vi.advanceTimersByTimeAsync(3000)

    expect(state.status.value).toBe('done')
    expect(state.active.value).toBe(false)
    expect(FakeEventSource.latest.closed).toBe(true)
  })
})

describe('换任务', () => {
  it('切到另一门课就关掉旧流、开新流', async () => {
    const jobId = ref('j1')
    const scope = effectScope()
    const state = scope.run(() => useGenerationStream(jobId))!
    const first = FakeEventSource.latest

    jobId.value = 'j2'
    await Promise.resolve()

    expect(first.closed).toBe(true)
    expect(FakeEventSource.latest.url).toBe('/api/courses/generate/j2/stream')
    expect(state.steps.value).toEqual([])
  })

  it('jobId 为空时不连流（工作台还没选课）', () => {
    const { state } = stream('')

    expect(FakeEventSource.instances).toHaveLength(0)
    expect(state.connected.value).toBe(false)
  })
})

describe('收尾', () => {
  it('scope 停掉时把连接关掉（不能留一条永远开着的流）', () => {
    const { state, scope } = stream()

    scope.stop()
    state.close()

    expect(FakeEventSource.latest.closed).toBe(true)
  })
})
