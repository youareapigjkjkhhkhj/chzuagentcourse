/**
 * 课程与生成接口层（P1 §4 的前端半边）。
 *
 * 前端不做业务判断，但**路径、方法、body 形状**必须和后端对齐 ——
 * 这几样写错，页面上的表现是「点了没反应」或者「保存了没生效」，
 * 排起来要翻两端代码。所以这里逐个钉住：每条前端调用打到哪个端点、
 * 带什么参数、拿回来的 data 直接就是业务数据（信封由 client 解掉）。
 */

import MockAdapter from 'axios-mock-adapter'
import { beforeEach, describe, expect, it } from 'vitest'

import * as api from '@/api'
import { http } from '@/api/client'
import type { OutlineSubmit } from '@/types/api'

let mock: MockAdapter

beforeEach(() => {
  mock = new MockAdapter(http)
})

/**
 * 后端成功响应的信封（P0-B1）。
 *
 * 返回的是 `[status, body]` 元组，用的时候**摊开**（`.reply(...ok(x))`）：
 * 假适配器只认「函数返回值」或「两个参数」两种写法，直接塞一个数组进去
 * 会被当成整个响应体，得到一个 HTTP 200 但解不出信封的怪响应。
 */
function ok(data: unknown): [number, Record<string, unknown>] {
  return [200, { code: 0, message: 'ok', data, requestId: 'r1' }]
}

describe('生成入口', () => {
  it('开始生成打的是 POST /courses/generate，body 是主题与模式', async () => {
    let body: unknown
    mock.onPost('/courses/generate').reply((config) => {
      body = JSON.parse(String(config.data))
      return ok({ courseId: 'c1', jobId: 'j1', status: 'queued', stream: '/x' })
    })

    const result = await api.startGeneration({ topic: '机器学习入门', mode: 'seminar' })

    expect(body).toEqual({ topic: '机器学习入门', mode: 'seminar' })
    expect(result).toMatchObject({ courseId: 'c1', jobId: 'j1' })
  })

  it('SSE 地址就是后端那条流（工作台据此订阅进度）', () => {
    expect(api.streamUrl('j1')).toBe('/api/courses/generate/j1/stream')
  })
})

describe('课程列表与详情', () => {
  it('列表带上状态与分页', async () => {
    let params: Record<string, unknown> = {}
    mock.onGet('/courses').reply((config) => {
      params = config.params ?? {}
      return ok({ items: [], total: 0, page: 1, size: 12 })
    })

    await api.fetchCourses({ status: 'ready', page: 2, size: 12 })

    expect(params).toEqual({ status: 'ready', page: 2, size: 12 })
  })

  it('详情可以按需带上整份页面内容', async () => {
    let params: Record<string, unknown> = {}
    mock.onGet('/courses/c1').reply((config) => {
      params = config.params ?? {}
      return ok({ id: 'c1', title: '课' })
    })

    const detail = await api.fetchCourse('c1', { withPages: true })

    expect(params).toEqual({ withPages: '1' })
    expect(detail).toMatchObject({ id: 'c1' })
  })

  it('删除课程打的是 DELETE（软删，后端保留页面与版本）', async () => {
    let method = ''
    mock.onDelete('/courses/c1').reply((config) => {
      method = String(config.method).toUpperCase()
      return ok({ id: 'c1', deletedAt: '2026-09-12T00:00:00Z' })
    })

    await api.deleteCourse('c1')

    expect(method).toBe('DELETE')
  })
})

describe('大纲', () => {
  it('取大纲打的是 GET /courses/{id}/outline', async () => {
    mock.onGet('/courses/c1/outline').reply(...ok({ courseId: 'c1', chapters: [], pageCount: 0 }))

    const tree = await api.fetchOutline('c1')

    expect(tree).toMatchObject({ courseId: 'c1', pageCount: 0 })
  })

  it('确认大纲打的是 POST，body 原样是那份章节树', async () => {
    let body: unknown
    mock.onPost('/courses/c1/outline').reply((config) => {
      body = JSON.parse(String(config.data))
      return ok({ courseId: 'c1', pageCount: 11 })
    })
    const outline: OutlineSubmit = {
      title: '机器学习入门',
      chapters: [{ no: 1, title: '第 1 章', pages: [{ kind: 'concept', title: '什么是模型' }] }],
    }

    const result = await api.confirmOutline('c1', outline)

    expect(body).toEqual(outline)
    expect(result).toMatchObject({ pageCount: 11 })
  })
})

describe('页面编辑', () => {
  it('取单页打的是 GET /courses/{id}/pages/{no}', async () => {
    mock.onGet('/courses/c1/pages/7').reply(...ok({ pageNo: 7, kind: 'concept', dsl: {} }))

    const page = await api.fetchPage('c1', 7)

    expect(page).toMatchObject({ pageNo: 7 })
  })

  it('保存只提交改动过的字段（空保存会把 rev 白白推上去）', async () => {
    let body: unknown
    mock.onPut('/courses/c1/pages/7').reply((config) => {
      body = JSON.parse(String(config.data))
      return ok({ pageNo: 7, rev: 2 })
    })

    await api.savePage('c1', 7, { narration: [{ text: '换个说法。' }] })

    expect(body).toEqual({ narration: [{ text: '换个说法。' }] })
  })

  it('AI 重写打的是 POST /rewrite，带上用户指令', async () => {
    let body: unknown
    mock.onPost('/courses/c1/pages/7/rewrite').reply((config) => {
      body = JSON.parse(String(config.data))
      return ok({ page: { pageNo: 7, rev: 3 }, tokens: 321, model: 'stub' })
    })

    const result = await api.rewritePage('c1', 7, '更通俗')

    expect(body).toEqual({ instruction: '更通俗' })
    expect(result.page.rev).toBe(3)
  })

  it('版本链打的是 GET /versions', async () => {
    mock.onGet('/courses/c1/pages/7/versions').reply(...ok({ items: [{ rev: 2 }, { rev: 1 }] }))

    const versions = await api.fetchVersions('c1', 7)

    expect(versions.items.map((row) => row.rev)).toEqual([2, 1])
  })
})

describe('任务操作', () => {
  it('轮询兜底打的是 GET /jobs/{id}', async () => {
    mock.onGet('/jobs/j1').reply(...ok({ id: 'j1', status: 'running', progress: 40, steps: [] }))

    const job = await api.fetchJob('j1')

    expect(job).toMatchObject({ id: 'j1', progress: 40 })
  })

  it('取消打的是 POST /cancel', async () => {
    let method = ''
    mock.onPost('/jobs/j1/cancel').reply((config) => {
      method = String(config.method).toUpperCase()
      return ok({ id: 'j1', status: 'canceled' })
    })

    await api.cancelJob('j1')

    expect(method).toBe('POST')
  })

  it('重试失败步骤打的是 POST /steps/{stepId}/retry', async () => {
    let url = ''
    mock.onPost(/\/jobs\/j1\/steps\/s3\/retry/).reply((config) => {
      url = String(config.url)
      return ok({ jobId: 'j1', stepId: 's3', status: 'queued' })
    })

    await api.retryStep('j1', 's3')

    expect(url).toBe('/jobs/j1/steps/s3/retry')
  })
})
