/**
 * 导出历史与产物（P5-F5-6 / F5-1~F5-5）—— 导出面板的唯一事实入口。
 *
 * 三条纪律：
 *
 * 1. **进度是问来的，不是算的**。渲染在后台跑，`progress` 是「画完几页 / 共几页」，
 *    所以列表里只要有排队中或导出中的行，就按 `POLL_INTERVAL_MS` 回问一次；
 *    全都停了就停轮询（一直问下去等于让一个开着抽屉去吃饭的页面白烧请求）。
 * 2. **下载链接是现签的**。`fileUrl` 带一次性票据，每次查询都会换一张新的，
 *    列表里那份**一律是空的** —— 所以点下载时先 `fetchExport` 取一张新票再用。
 *    缓存上一次那张的结局是「下载失败」，而用户看不出这是过期还是别的。
 * 3. **失败可以重来，但重来是新的一次**。一行 = 一次导出，所以「重试」不是
 *    改这一行的状态，而是拿同样的格式与选项再建一次 —— 上一行留着，
 *    它记着那次为什么失败（`error`）。
 */

import { computed, ref, watch, type Ref } from 'vue'

import * as api from '@/api'
import { usePolling } from '@/composables/usePolling'
import type {
  ExportCreatePayload,
  ExportFormat,
  ExportItem,
  ExportScope,
  ExportTemplate,
} from '@/types/api'

/** 轮询间隔。渲染一份 12 页的课件是秒级的，这个节奏够跟上又不会把接口打满。 */
const POLL_INTERVAL_MS = 1500

export function useExports(courseId: Ref<string>) {
  const items = ref<ExportItem[]>([])
  /** 每种范围支持哪些格式 —— 铺选项用它，前端不写死一份会过期的表。 */
  const supported = ref<Record<ExportScope, ExportFormat[]>>({ course: [], record: [] })
  /** 可选的 PPT 模板（配色+字体），同样由后端下发。 */
  const templates = ref<ExportTemplate[]>([])
  const loading = ref(false)
  const hasMore = ref(false)
  /** 读取失败时的一句话（历史列表读不出来，不等于导出不能用）。 */
  const error = ref('')

  /** 还有没跑完的那几个。有就轮询，没有就不问。 */
  const inFlight = computed(() =>
    items.value.some((row) => row.status === 'queued' || row.status === 'running'),
  )

  const polling = usePolling(() => void load(), POLL_INTERVAL_MS)
  watch(inFlight, (busy) => (busy ? polling.start() : polling.stop()))

  /** 拉第一页历史。**不合并**：服务端那份是权威，本地维护一份列表迟早会和它对不上。 */
  async function load(): Promise<void> {
    const id = courseId.value
    if (!id) return
    loading.value = true
    try {
      const page = await api.fetchCourseExports(id)
      items.value = page.items
      supported.value = page.supported
      templates.value = page.templates ?? []
      hasMore.value = page.hasMore
      error.value = ''
    } catch {
      error.value = '导出历史读取失败，稍后再试'
    } finally {
      loading.value = false
    }
  }

  /**
   * 建一次导出。返回新那一行（失败返回 `null`，原因由调用方提示）。
   *
   * 建完立刻插到列表头再问一次：接口是「立刻返回」的，等下一次轮询才显示的话，
   * 用户点完按钮会有一秒多的空白，以为没点上。
   */
  async function create(payload: ExportCreatePayload): Promise<ExportItem | null> {
    const id = courseId.value
    if (!id) return null
    const row = await api.createExport(id, payload)
    items.value = [row, ...items.value]
    polling.start()
    return row
  }

  /** 「重试」= 拿同样的格式与选项再导一次（见模块 docstring 第 3 条）。 */
  function retry(row: ExportItem): Promise<ExportItem | null> {
    return create({
      format: row.format,
      scope: row.scope,
      sessionId: row.sessionId || undefined,
      options: row.options,
    })
  }

  async function remove(exportId: string): Promise<void> {
    await api.deleteExport(exportId)
    items.value = items.value.filter((row) => row.exportId !== exportId)
  }

  /**
   * 下载。**先问一次状态再点**：`fileUrl` 是一次性票据，列表里那份是空的。
   *
   * 产物过期或已被清理时服务端回 409/404（信封里说得清原因），照原样抛给调用方。
   */
  async function download(exportId: string): Promise<void> {
    const fresh = await api.fetchExport(exportId)
    if (!fresh.fileUrl) throw new Error('这份产物现在取不到下载链接，重新导出一次')
    // 用 a 标签而不是 `location.href = …`：后者在浏览器偶尔会因为
    // 「下载被当成一次导航」把当前页面刷掉，而用户正开着导出历史。
    const link = document.createElement('a')
    link.href = fresh.fileUrl
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
  }

  return {
    items,
    supported,
    templates,
    loading,
    hasMore,
    error,
    inFlight,
    load,
    create,
    retry,
    remove,
    download,
  }
}
