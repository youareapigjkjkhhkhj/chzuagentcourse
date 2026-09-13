/**
 * HTTP 客户端（P0 §7）。
 *
 * 只做三件事：
 * 1. 统一注入 `X-Request-Id` —— 前后端对着同一个 id 查日志（P0-B1）
 * 2. 统一解包 `{code, message, data, requestId}`，成功时直接给业务数据
 * 3. `code !== 0` 一律抛 ApiError，页面上再也没机会忘记判错
 *
 * ★ 浏览器侧不出现任何厂商凭据：这里只会请求自己的 /api，
 *   厂商的 Key / 端点全在服务端（AGENTS.md §4.1）。
 */

import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig } from 'axios'

import type { Envelope } from '@/types/api'

/** 业务异常。`code` 用后端的段位：4xxxx 客户端 / 5xxxx 服务端。 */
export class ApiError extends Error {
  readonly code: number
  readonly data: unknown
  readonly requestId: string

  constructor(code: number, message: string, data: unknown = null, requestId = '') {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.data = data
    this.requestId = requestId
  }

  /** 40201：能力未配置。前端据此弹「去设置页」的引导，而不是「服务器错误」。 */
  get isNotConfigured(): boolean {
    return this.code === 40201
  }
}

/** 网络层失败（后端没起来 / 断网 / 超时）统一成这个码，跟后端段位不冲突。 */
export const NETWORK_ERROR_CODE = -1

/** 40304：开了站点访问码，而这次请求没带（P5-A13）。 */
export const ACCESS_REQUIRED_CODE = 40304

/** 访问码校验页。由后端渲染（它不能依赖被它挡住的前端产物）。 */
export const ACCESS_GATE_PATH = '/access'

/**
 * 没进门时**整页跳过去**，而不是弹一个报错。
 *
 * 拿 `window.location.href` 而不是路由 push：那一刻这个页面的接口全是 403，
 * 前端自己也不知道该渲染什么；而校验页是后端渲染的另一份文档。
 *
 * 用 `location.replace` 而不是 `assign`：跳过去之后按返回键不该又弹回这个
 * 一片报错的页面 —— 用户要回去的是他刚才在的那个位置，而那个位置已经记在
 * 校验页的 `next` 里了。
 */
function gotoAccessGate(): void {
  const next = `${window.location.pathname}${window.location.search}`
  window.location.replace(`${ACCESS_GATE_PATH}?next=${encodeURIComponent(next)}`)
}

export function newRequestId(): string {
  // crypto.randomUUID 在非安全上下文（http 非 localhost）不可用，留个退路
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function isEnvelope(value: unknown): value is Envelope<unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    'code' in value &&
    'message' in value &&
    'data' in value
  )
}

/** 后端前缀。`EventSource` 不走 axios，得自己拼全路径，所以放这里当唯一来源。 */
export const API_BASE = '/api'

export const http: AxiosInstance = axios.create({
  baseURL: API_BASE,
  // 探活与生成都可能要等上游，60s 是「足够长但不至于让人以为页面卡死」的值
  timeout: 60_000,
  // ★ 这里**不要**写死 `Content-Type: application/json`。
  //   axios 的规则是：data 是 FormData、而现有 Content-Type 里含 application/json
  //   时，直接把 FormData 序列化成 JSON（`formDataToJSON`）发出去 —— 音频与材料
  //   上传就是这么变成一坨 JSON 的，后端只回一句「只接受 pcm / wav 音频，收到
  //   'json'」，看上去像格式不对，其实是本地这一行把文件吞了。
  //   不写它反而两边都对：对象体 axios 自己补 application/json，
  //   FormData 让浏览器自己写 multipart/form-data; boundary=…。
})

http.interceptors.request.use((config) => {
  config.headers.set('X-Request-Id', newRequestId())
  return config
})

http.interceptors.response.use(
  (response) => {
    const body: unknown = response.data
    if (!isEnvelope(body)) {
      throw new ApiError(50001, '响应格式不符合约定（缺少信封字段）', body)
    }
    if (body.code !== 0) {
      throw new ApiError(body.code, body.message, body.data, body.requestId)
    }
    // 直接把 data 交出去：调用方拿到的就是业务数据本身
    response.data = body.data
    return response
  },
  (error: AxiosError) => {
    // 后端对错误也用信封（含 4xx/5xx），所以优先按信封解析，
    // 这样前端只需要理解一套错误形状。
    const body: unknown = error.response?.data
    if (isEnvelope(body)) {
      if (body.code === ACCESS_REQUIRED_CODE) {
        // 页面正在被换掉，这里不必（也不该）再往上抛一个没人看的错
        gotoAccessGate()
      }
      return Promise.reject(
        new ApiError(body.code, body.message, body.data, body.requestId),
      )
    }
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
      return Promise.reject(new ApiError(NETWORK_ERROR_CODE, '请求超时，请检查网络或稍后重试'))
    }
    if (!error.response) {
      return Promise.reject(
        new ApiError(NETWORK_ERROR_CODE, '连接不上后端服务，请确认它已经启动（make dev）'),
      )
    }
    return Promise.reject(
      new ApiError(50001, `请求失败（HTTP ${error.response.status}）`, error.response.data),
    )
  },
)

export async function get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await http.get<T>(url, config)
  return response.data
}

export async function put<T>(url: string, body?: unknown): Promise<T> {
  const response = await http.put<T>(url, body)
  return response.data
}

export async function post<T>(url: string, body?: unknown): Promise<T> {
  const response = await http.post<T>(url, body)
  return response.data
}

export async function del<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await http.delete<T>(url, config)
  return response.data
}
