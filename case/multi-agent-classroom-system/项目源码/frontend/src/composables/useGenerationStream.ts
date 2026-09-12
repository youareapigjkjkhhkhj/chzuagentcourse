/**
 * 一次生成任务的进度（P1-B2 / B5）—— 工作台上唯一的事实入口。
 *
 * 两条纪律：
 *
 * 1. **前端不造进度**。`progress` / `steps` / `livePageNo` 里的每个数字都来自
 *    服务端：要么是一帧 SSE，要么是 `GET /api/jobs/{jobId}`。没有数据时进度是
 *    「未知」，不是 0% 也不是慢慢往上爬的假进度条。
 * 2. **断了就换条路问，而不是假装还在连**。一次 `onerror` 交给浏览器自己重连；
 *    连断两次就转去轮询 REST，直到某天又有帧进来再切回来。
 *
 * 耗时（`durationMs`）特意在 `step.done` 之后回问一次 REST —— SSE 那一帧里
 * 没有耗时，前端自己掐表算出来的数字和库里记的会是两个（重连、刷新页面
 * 都会对不上）。
 */

import { computed, onScopeDispose, ref, watch, type Ref } from 'vue'

import * as api from '@/api'
import { usePolling } from '@/composables/usePolling'
import { STEP_TYPE_LABELS } from '@/utils/labels'
import type { GenJobView, GenStep, JobStatus, LiveStep, StepType, WriteBatch } from '@/types/api'

/** 断两次才转轮询：第一次基本是浏览器在换连接，没必要多问一遍。 */
const FAILURES_BEFORE_POLLING = 2

/** 轮询间隔。比 SSE 慢得多是故意的 —— 它只是兜底。 */
const POLL_INTERVAL_MS = 3000

const TERMINAL_STATUSES: ReadonlySet<string> = new Set(['done', 'failed', 'canceled'])

/** SSE 帧的载荷是后端 `events.emit` 那一刻的形状，字段可能缺，一律当可选读。 */
interface FramePayload {
  jobId?: string
  courseId?: string
  steps?: { id: string; type: StepType; title: string; weight?: number }[]
  stepId?: string
  type?: StepType
  title?: string
  percent?: number
  progress?: number
  tokens?: number
  error?: string
  skipped?: boolean
  /** `page.ready` 的页号在顶层；`step.progress` 的在 `detail` 里。 */
  pageNo?: number
  detail?: { pageNo?: number; batches?: WriteBatch[]; [key: string]: unknown }
}

export function useGenerationStream(jobId: Ref<string>) {
  const connected = ref(false)
  const mode = ref<'stream' | 'polling'>('stream')
  const status = ref<JobStatus | ''>('')
  const progress = ref(0)
  const steps = ref<LiveStep[]>([])
  const livePageNo = ref(0)
  const batches = ref<WriteBatch[]>([])
  const readyPages = ref<number[]>([])
  const error = ref('')
  /** 任务还在跑（或等在确认点）。终态之后流就收了。 */
  const active = ref(true)
  /** 有没有从服务端拿到过任何一份数据。界面上「—」与「0%」的区别就在这里。 */
  const hasData = ref(false)

  let source: EventSource | null = null
  let failures = 0

  const polling = usePolling(poll, POLL_INTERVAL_MS)

  const percent = computed(() => (hasData.value ? progress.value : null))

  // --- 内部 ---

  function close(): void {
    polling.stop()
    const current = source
    source = null
    connected.value = false
    current?.close()
  }

  function finish(): void {
    active.value = false
    close()
  }

  function reset(): void {
    connected.value = false
    mode.value = 'stream'
    status.value = ''
    progress.value = 0
    steps.value = []
    livePageNo.value = 0
    batches.value = []
    readyPages.value = []
    error.value = ''
    hasData.value = false
    failures = 0
    active.value = true
  }

  /** 记下某一帧带来的步骤变化。没见过的步骤就按帧里说的补一行。 */
  function upsertStep(id: string, patch: Partial<LiveStep>): LiveStep {
    // 帧里没带的字段不该把已知的值抹成 undefined
    const clean = Object.fromEntries(
      Object.entries(patch).filter(([, value]) => value !== undefined),
    ) as Partial<LiveStep>
    const found = steps.value.find((row) => row.id === id)
    if (found) {
      Object.assign(found, clean)
      return found
    }
    const kind = clean.type ?? 'write'
    const created: LiveStep = {
      id,
      jobId: jobId.value,
      seq: steps.value.length + 1,
      type: kind,
      title: STEP_TYPE_LABELS[kind],
      status: 'wait',
      detail: {},
      durationMs: 0,
      tokens: 0,
      error: '',
      startedAt: null,
      finishedAt: null,
      percent: 0,
      ...clean,
    }
    steps.value = [...steps.value, created]
    return created
  }

  /**
   * 用 REST 那份覆盖本地状态（轮询兜底、`step.done` 后回问耗时都走这里）。
   *
   * 只覆盖步骤与进度：`readyPages` / `livePageNo` 是 SSE 才有的实时信息，
   * REST 里没有对应的字段，不能被抹掉。
   */
  function applyJob(job: GenJobView): void {
    hasData.value = true
    status.value = job.status
    progress.value = typeof job.progress === 'number' ? job.progress : progress.value
    const known = new Map(steps.value.map((row) => [row.id, row.percent]))
    steps.value = (job.steps ?? []).map((step: GenStep) => ({
      ...step,
      percent: known.get(step.id) ?? 0,
    }))
    if (TERMINAL_STATUSES.has(job.status)) {
      error.value = job.status === 'failed' ? job.error || error.value : ''
      finish()
    }
  }

  /**
   * 问一次 REST。用 `.then` 而不是 `await`：`step.done` 的处理必须是同步返回的
   * （调用方紧接着就会读状态），而这一步只是去补一个耗时。
   */
  function syncJob(): void {
    try {
      api.fetchJob(jobId.value).then(applyJob, () => {
        // 拉不到就保持 SSE 给的那份：这里失败不代表流断了
      })
    } catch {
      // 同上门：一帧事件不该把整条流打断
    }
  }

  function startPolling(): void {
    mode.value = 'polling'
    syncJob() // 立刻问一次，别让用户干等一个间隔
    polling.start()
  }

  /** 又有帧进来了 —— 说明流自己接上了，轮询可以停了。 */
  function backToStream(): void {
    polling.stop()
    mode.value = 'stream'
    connected.value = true
    failures = 0
  }

  function poll(): void {
    syncJob()
  }

  // --- 事件 ---

  const HANDLERS: Record<string, (payload: FramePayload) => void> = {
    'job.start': (payload) => {
      steps.value = (payload.steps ?? []).map((step, index) => ({
        id: step.id,
        jobId: payload.jobId ?? jobId.value,
        seq: index + 1,
        type: step.type,
        title: step.title,
        status: 'wait' as const,
        detail: {},
        durationMs: 0,
        tokens: 0,
        error: '',
        startedAt: null,
        finishedAt: null,
        percent: 0,
      }))
      if (typeof payload.progress === 'number') progress.value = payload.progress
    },

    'step.start': (payload) => {
      if (payload.stepId) {
        upsertStep(payload.stepId, {
          status: 'running',
          type: payload.type,
          ...(payload.title ? { title: payload.title } : {}),
        })
      }
    },

    'step.progress': (payload) => {
      if (payload.stepId) {
        const step = upsertStep(payload.stepId, { status: 'running', type: payload.type })
        if (typeof payload.percent === 'number') step.percent = payload.percent
      }
      if (typeof payload.progress === 'number') progress.value = payload.progress
      const detail = payload.detail ?? {}
      if (typeof detail.pageNo === 'number') livePageNo.value = detail.pageNo
      if (Array.isArray(detail.batches)) batches.value = detail.batches
    },

    'step.done': (payload) => {
      if (payload.stepId) {
        const step = upsertStep(payload.stepId, {
          status: payload.skipped ? 'skipped' : 'done',
          type: payload.type,
        })
        step.percent = 100
        if (typeof payload.tokens === 'number') step.tokens = payload.tokens
      }
      if (typeof payload.progress === 'number') progress.value = payload.progress
      syncJob() // 耗时以库里那份为准
    },

    'step.failed': (payload) => {
      if (payload.stepId) {
        upsertStep(payload.stepId, {
          status: 'failed',
          type: payload.type,
          error: payload.error ?? '',
        })
      }
      if (typeof payload.progress === 'number') progress.value = payload.progress
    },

    'page.ready': (payload) => {
      const pageNo = payload.detail?.pageNo ?? payload.pageNo
      if (typeof pageNo === 'number' && !readyPages.value.includes(pageNo)) {
        readyPages.value = [...readyPages.value, pageNo].sort((a, b) => a - b)
      }
    },

    'job.paused': (payload) => {
      status.value = 'paused'
      if (typeof payload.progress === 'number') progress.value = payload.progress
    },

    'job.done': () => {
      status.value = 'done'
      error.value = ''
      finish()
    },

    'job.failed': (payload) => {
      status.value = 'failed'
      error.value = payload.error ?? ''
      finish()
    },

    'job.canceled': () => {
      status.value = 'canceled'
      error.value = ''
      finish()
    },
  }

  function connect(id: string): void {
    const stream = new EventSource(api.streamUrl(id))
    source = stream
    connected.value = true

    for (const [name, handler] of Object.entries(HANDLERS)) {
      stream.addEventListener(name, (event) => {
        if (!active.value) return
        const payload = parseFrame(event)
        if (payload === null) return
        if (mode.value === 'polling') backToStream()
        hasData.value = true
        handler(payload)
      })
    }

    stream.onerror = () => {
      // 浏览器会自己重连，这里不做任何「重连」动作，只记一次数
      connected.value = false
      failures += 1
      if (mode.value === 'stream' && failures >= FAILURES_BEFORE_POLLING) startPolling()
    }
  }

  function open(id: string): void {
    close()
    reset()
    if (!id) return // 还没选课程：不连流，也不假装连着
    // 先问一次「现在到哪了」：从首页点进工作台时任务多半已经跑了一半，
    // 早先那几帧 SSE 是收不回来的，只靠流的话六步要等到下一次事件才出现。
    syncJob()
    connect(id)
  }

  watch(jobId, (id) => open(id), { immediate: true })
  onScopeDispose(close)

  return {
    connected,
    mode,
    status,
    progress,
    percent,
    steps,
    livePageNo,
    batches,
    readyPages,
    error,
    active,
    hasData,
    /** 立刻回问一次 REST。重试一步之后用它把「那一步现在什么状态」问出来，
     *  不必等下一个 SSE 帧 —— 重试后服务端不一定马上发帧。 */
    refresh: syncJob,
    close,
  }
}

/** 一帧的 `data:` 是 JSON 字符串。解析不了就丢掉这一帧 —— 界面宁可少一帧，
 *  也不该因为一条坏帧把整个流打断（重连之后还会收到完整状态）。 */
function parseFrame(event: Event): FramePayload | null {
  const raw = (event as MessageEvent).data
  if (typeof raw !== 'string' || !raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    return typeof parsed === 'object' && parsed !== null ? (parsed as FramePayload) : null
  } catch {
    return null
  }
}
