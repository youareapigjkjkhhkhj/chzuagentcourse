/**
 * HTTP 客户端（P0-B1：前端只写一套解包逻辑）。
 *
 * 这里测的不是 axios，而是**我们对信封的约定**：
 * 业务码与 HTTP 状态是两回事，200 也可能是失败。
 */

import MockAdapter from 'axios-mock-adapter'
import { beforeEach, describe, expect, it } from 'vitest'

import { ApiError, http, newRequestId, NETWORK_ERROR_CODE } from '@/api/client'

let mock: MockAdapter

beforeEach(() => {
  mock = new MockAdapter(http)
})

describe('响应解包', () => {
  it('code=0 时直接给出 data', async () => {
    mock.onGet('/health').reply(200, {
      code: 0,
      message: 'ok',
      data: { status: 'ok' },
      requestId: 'r1',
    })

    const response = await http.get('/health')

    expect(response.data).toEqual({ status: 'ok' })
  })

  it('code!=0 时抛 ApiError，带上业务码与文案', async () => {
    mock.onPut('/settings/providers/openai').reply(400, {
      code: 40001,
      message: '「pageCount」必须是 8 ~ 20 之间的整数',
      data: null,
      requestId: 'r2',
    })

    await expect(http.put('/settings/providers/openai')).rejects.toMatchObject({
      code: 40001,
      message: '「pageCount」必须是 8 ~ 20 之间的整数',
    })
  })

  it('HTTP 200 也可能是失败 —— 只看业务码', async () => {
    mock.onPost('/settings/providers/deepseek/test').reply(200, {
      code: 40201,
      message: '未配置 API Key',
      data: { ok: false, error: 'missing_api_key' },
      requestId: 'r3',
    })

    const failure = await http
      .post('/settings/providers/deepseek/test')
      .catch((error: unknown) => error)

    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).isNotConfigured).toBe(true)
    expect((failure as ApiError).data).toEqual({ ok: false, error: 'missing_api_key' })
  })

  it('响应不是信封形状时报 50001，而不是把 undefined 交给页面', async () => {
    mock.onGet('/health').reply(200, '<html>代理返回了 HTML</html>')

    await expect(http.get('/health')).rejects.toMatchObject({ code: 50001 })
  })

  it('连不上后端时给一句能照着做的话', async () => {
    mock.onGet('/health').networkError()

    const failure = (await http.get('/health').catch((error: unknown) => error)) as ApiError

    expect(failure.code).toBe(NETWORK_ERROR_CODE)
    expect(failure.message).toContain('后端服务')
  })

  it('超时单独给文案，不说「网络错误」', async () => {
    mock.onGet('/health').timeout()

    const failure = (await http.get('/health').catch((error: unknown) => error)) as ApiError

    expect(failure.code).toBe(NETWORK_ERROR_CODE)
    expect(failure.message).toContain('超时')
  })
})

describe('请求头', () => {
  it('每个请求都带一个非空的 X-Request-Id', async () => {
    mock.onGet('/health').reply((config) => {
      const id = config.headers?.['X-Request-Id']
      expect(typeof id).toBe('string')
      expect(String(id).length).toBeGreaterThan(0)
      return [200, { code: 0, message: 'ok', data: {}, requestId: String(id) }]
    })

    await http.get('/health')

    expect(mock.history.get).toHaveLength(1)
  })

  it('newRequestId 每次都不一样', () => {
    expect(newRequestId()).not.toBe(newRequestId())
  })
})
