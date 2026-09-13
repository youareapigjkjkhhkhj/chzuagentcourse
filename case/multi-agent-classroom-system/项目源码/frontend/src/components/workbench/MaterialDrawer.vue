<script setup lang="ts">
/**
 * 右栏：材料抽屉（P4 §6 / F4-1~F4-6 / F4-14）。
 *
 * 三块内容从上到下：**上传区**（拖进来就传，解析在后台）、**材料列表**
 * （状态、页数、分块数、是否已加入这门课）、**预览**（目录树 + 分块原文 +
 * 命中高亮）。点某个材料的名字才展开预览 —— 抽屉窄，一屏塞两份内容是看不清的。
 *
 * 几个刻意的取舍：
 *
 * 1. **解析中才轮询**。上传完 `status=parsing`，前端每 2 秒问一次；一旦全部
 *    就绪就停（`stopPolling`）。常驻的定时器会把「不动了」和「问不着了」
 *    混成一件事。
 * 2. **删除要二次确认，且确认框里的数字来自服务端**（`40901` 的 `details.impact`）。
 *    前端不自己数「有几页引用了它」——那是库里的账，猜错一次就是一次误导。
 * 3. **搜索是边打边搜的**，而且只搜这门课关联的材料（没关联就搜全部）：
 *    工作台里搜材料，问的是「我手上这门课能用什么」。
 */
import { computed, nextTick, onScopeDispose, ref, watch } from 'vue'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'

import { ApiError, NETWORK_ERROR_CODE } from '@/api/client'
import * as api from '@/api'
import { describeError } from '@/stores/settings'
import type {
  MaterialChunk,
  MaterialDetail,
  MaterialHit,
  MaterialItem,
} from '@/types/api'

const props = defineProps<{
  courseId: string
  collapsed: boolean
}>()

const emit = defineEmits<{
  'update:collapsed': [value: boolean]
  /**
   * 出处打不开了：工作台把徽标画成失效态（P4-A13）。
   *
   * 键有两种粒度，对应两种坏法：`材料id:分块id` = 这一段取不到（材料重新
   * 解析过），`材料id` = 整份材料没了（用户删的）—— 后者一次带走它所有出处。
   */
  missing: [key: string]
}>()

const CHUNK_PAGE_SIZE = 20
const ACCEPT = '.md,.txt,.pdf,.docx,.pptx,.xlsx'

const materials = ref<MaterialItem[]>([])
const attachedIds = ref<string[]>([])
const detail = ref<MaterialDetail | null>(null)
const chunks = ref<MaterialChunk[]>([])
const chunkPage = ref(1)
const chunkTotal = ref(0)
const focusChunk = ref('')
/** 聚焦那一段的引文（来自徽标上的 `quote`，后端核对过的一字不差片段）。 */
const focusQuote = ref('')
const query = ref('')
const hits = ref<MaterialHit[]>([])
const loading = ref(false)
const searching = ref(false)
const uploading = ref(false)
const uploadingName = ref('')
const error = ref('')
/** 「连不上后端」与「这份材料有问题」是两回事，提示的配色也不同。 */
const errorIsNetwork = ref(false)
/** 刚传上去、等它解析完就自动打开的那一份。 */
const pendingOpen = ref('')
const fileEl = ref<HTMLInputElement | null>(null)

const attachedSet = computed(() => new Set(attachedIds.value))
const parsing = computed(() => materials.value.filter((item) => item.status === 'parsing').length)
const hasMoreChunks = computed(() => chunks.value.length < chunkTotal.value)

/** 只看这门课在用的那几份（F4-14）。 */
const onlyAttached = ref(false)

/**
 * 屏幕上列出来的材料。
 *
 * 默认列**全部**：这一栏主要是拿来「挑一份加进来」的，只列已加入的话，
 * 想加第二份时反而找不到入口。用户自己点「只看已加入」时才收窄。
 */
const shown = computed(() =>
  onlyAttached.value ? materials.value.filter((item) => attachedSet.value.has(item.fileId)) : materials.value,
)

/* --- 读 --- */

/** 记一次错误：文案给用户，`errorIsNetwork` 给配色。 */
function showError(err: unknown): void {
  error.value = describeError(err)
  errorIsNetwork.value = err instanceof ApiError && err.code === NETWORK_ERROR_CODE
}

async function load(): Promise<void> {
  const id = props.courseId
  if (!id) {
    materials.value = []
    attachedIds.value = []
    return
  }
  loading.value = true
  try {
    const [list, attached] = await Promise.all([
      api.fetchMaterials({ size: 200 }),
      api.fetchCourseMaterials(id),
    ])
    materials.value = list.items
    attachedIds.value = attached.items.map((item) => item.fileId)
    error.value = ''
    errorIsNetwork.value = false
  } catch (err) {
    showError(err)
  } finally {
    loading.value = false
  }
}

async function openMaterial(fileId: string, chunkId = ''): Promise<void> {
  try {
    detail.value = await api.fetchMaterial(fileId)
    chunkPage.value = 1
    await loadChunks()
    focusChunk.value = chunkId
    if (!chunkId) focusQuote.value = ''
    if (chunkId) await locate(chunkId)
  } catch (err) {
    detail.value = null
    chunks.value = []
    MessagePlugin.error(describeError(err))
  }
}

async function loadChunks(append = false): Promise<void> {
  const material = detail.value
  if (!material) return
  const data = await api.fetchMaterialChunks(material.fileId, {
    page: chunkPage.value,
    size: CHUNK_PAGE_SIZE,
  })
  chunkTotal.value = data.total
  chunks.value = append ? [...chunks.value, ...data.items] : data.items
}

/** 找到那一块所在的页，翻过去，再把它滚到眼前。 */
async function locate(chunkId: string): Promise<void> {
  const material = detail.value
  if (!material) return
  let target = chunks.value.find((item) => item.chunkId === chunkId)
  if (!target) {
    try {
      const chunk = await api.fetchMaterialChunk(material.fileId, chunkId)
      const page = Math.max(1, Math.ceil(chunk.chunkNo / CHUNK_PAGE_SIZE))
      chunkPage.value = page
      await loadChunks()
      target = chunks.value.find((item) => item.chunkId === chunkId)
    } catch {
      emit('missing', `${material.fileId}:${chunkId}`)
      MessagePlugin.warning('这条出处对应的原文找不到了（材料可能已删除）')
      return
    }
  }
  if (!target) return
  await nextTick()
  document.getElementById(`chunk-${chunkId}`)?.scrollIntoView({ block: 'center' })
}

/* --- 上传 --- */

async function upload(file: File): Promise<void> {
  if (!props.courseId) {
    MessagePlugin.warning('先选一门课再传材料')
    return
  }
  uploading.value = true
  uploadingName.value = file.name
  error.value = ''
  try {
    const item = await api.uploadMaterial(file)
    if (item.duplicated) {
      MessagePlugin.info(`「${item.name}」已经在材料库里了，没有重复解析`)
    } else {
      MessagePlugin.success(`「${item.name}」上传成功，正在解析`)
      pendingOpen.value = item.fileId
    }
    await load()
  } catch (err) {
    // 413 / 415 都带后端写好的那句话（文件过大 / 不支持的格式），原样说出来
    showError(err)
    MessagePlugin.error(error.value)
  } finally {
    uploading.value = false
    uploadingName.value = ''
  }
}

function onPick(event: Event): void {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = '' // 同一个文件连传两次也要能触发 change
  files.forEach((file) => void upload(file))
}

function onDrop(event: DragEvent): void {
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (!files.length) return
  emit('update:collapsed', false)
  files.forEach((file) => void upload(file))
}

/* --- 与课程的关系 --- */

async function attach(fileId: string): Promise<void> {
  try {
    await api.attachMaterials(props.courseId, [fileId])
    await load()
    MessagePlugin.success('已加入这门课，生成与重写时会检索它')
  } catch (err) {
    MessagePlugin.error(describeError(err))
  }
}

async function detach(fileId: string): Promise<void> {
  try {
    const result = await api.detachMaterial(props.courseId, fileId)
    await load()
    MessagePlugin.info(
      result.affectedCitations
        ? `已从这门课移除，${result.affectedCitations} 处引用不再更新`
        : '已从这门课移除',
    )
  } catch (err) {
    MessagePlugin.error(describeError(err))
  }
}

/** 删除材料：被引用着时第一次一定被挡下来，把影响面摊开再问一次（P4-A13）。 */
async function remove(fileId: string): Promise<void> {
  const item = materials.value.find((row) => row.fileId === fileId)
  try {
    await api.deleteMaterial(fileId)
    afterRemove(fileId, item)
  } catch (err) {
    if (!(err instanceof ApiError) || err.code !== 40901) {
      MessagePlugin.error(describeError(err))
      return
    }
    const data = (err.data ?? {}) as { impact?: { pages?: number; citations?: number } }
    const pages = data.impact?.pages ?? 0
    const dialog = DialogPlugin.confirm({
      header: '这份材料还在被引用',
      body: `有 ${pages} 页引用了它，删掉之后这些溯源徽标会变成失效态（页面内容不动）。确定删除？`,
      confirmBtn: '删除',
      cancelBtn: '算了',
      theme: 'warning',
      onConfirm: async () => {
        dialog.destroy()
        try {
          await api.deleteMaterial(fileId, { force: true })
          afterRemove(fileId, item)
        } catch (again) {
          MessagePlugin.error(describeError(again))
        }
      },
      onCancel: () => dialog.destroy(),
    })
  }
}

function afterRemove(fileId: string, item?: MaterialItem): void {
  if (detail.value?.fileId === fileId) {
    detail.value = null
    chunks.value = []
  }
  materials.value = materials.value.filter((row) => row.fileId !== fileId)
  // 整份材料没了 → 它的每一条出处都失效。刚才那句「这些溯源徽标会变成失效态」
  // 得当场兑现：等用户点了徽标才发现，就成了界面上的一句空话（P4-A13）。
  emit('missing', fileId)
  MessagePlugin.success(`已删除「${item?.name ?? fileId}」`)
}

/* --- 检索 --- */

let searchTimer: ReturnType<typeof setTimeout> | null = null

watch(query, (value) => {
  if (searchTimer) clearTimeout(searchTimer)
  const text = value.trim()
  if (!text) {
    hits.value = []
    searching.value = false
    return
  }
  searching.value = true
  // 边打边搜：等手上这一下停了再发（不然「倒排索引」要发四次）
  searchTimer = setTimeout(() => void doSearch(text), 300)
})

async function doSearch(text: string): Promise<void> {
  try {
    // 这门课关联了材料就只搜它们 —— 工作台里问的是「这门课能用什么」
    const fileIds = attachedIds.value.length ? attachedIds.value : undefined
    const data = await api.searchMaterials({ q: text, fileIds, topK: 8 })
    hits.value = data.items
  } catch (err) {
    hits.value = []
    showError(err)
  } finally {
    searching.value = false
  }
}

/* --- 解析轮询 --- */

let timer: ReturnType<typeof setInterval> | null = null

function stopPolling(): void {
  if (timer) clearInterval(timer)
  timer = null
}

function syncPolling(): void {
  if (parsing.value > 0 && !timer) {
    timer = setInterval(() => void tick(), 2000)
  } else if (!parsing.value) {
    stopPolling()
  }
}

async function tick(): Promise<void> {
  const list = await api.fetchMaterials({ size: 200 }).catch(() => null)
  if (!list) return
  materials.value = list.items
  const current = detail.value
  if (current) {
    const row = list.items.find((item) => item.fileId === current.fileId)
    if (row && row.status !== current.status) {
      detail.value = { ...current, ...row }
      if (row.status === 'ready') await loadChunks()
    }
  }
  // 刚上传的那份解析完了：自动展开它（P4 §6「解析完成自动展开预览」）
  if (pendingOpen.value) {
    const row = list.items.find((item) => item.fileId === pendingOpen.value)
    if (row?.status === 'ready') {
      const target = pendingOpen.value
      pendingOpen.value = ''
      await openMaterial(target)
    } else if (row?.status === 'failed') {
      pendingOpen.value = ''
      MessagePlugin.error(`「${row.name}」解析失败：${row.error || '原因见后端日志'}`)
    }
  }
}

watch(parsing, syncPolling)
onScopeDispose(stopPolling)

/* --- 高亮 --- */

function escapeHtml(text: string): string {
  return text.replace(
    /[&<>"']/g,
    (char) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] as string,
  )
}

/**
 * 把命中的那一段原文包成 `<mark>`。
 *
 * 原文与引文都先转义再插入 —— 材料是用户自己传的文件，里面的 `<script>`
 * 不该借这条路跑起来。找不到就原样返回（后端对引文做过归一化，偶尔会差几个
 * 空白字符），**绝不为了高亮去猜位置**。
 */
function highlight(text: string, quote: string): string {
  const body = escapeHtml(text)
  const needle = escapeHtml(quote || '').trim()
  const index = needle ? body.indexOf(needle) : -1
  if (index < 0) return body
  return `${body.slice(0, index)}<mark>${needle}</mark>${body.slice(index + needle.length)}`
}

function hitQuote(hit: MaterialHit): string {
  const text = hit.text ?? ''
  if (!text) return ''
  const words = hit.matched.filter(Boolean)
  const at = words.length ? text.indexOf(words[0]) : -1
  const from = at > 40 ? at - 40 : 0
  return text.slice(from, from + 120)
}

/** 聚焦的那一块按**出处里那句原文**高亮，其余块整段显示（不高亮就没有误导）。 */
function bodyOf(chunk: MaterialChunk): string {
  return highlight(chunk.text, chunk.chunkId === focusChunk.value ? focusQuote.value : '')
}

function moreChunks(): void {
  chunkPage.value += 1
  void loadChunks(true)
}

/* --- 打开（外面点徽标 / 拖文件进来） --- */

async function focusSource(payload: {
  fileId: string
  chunkId: string
  page?: number | null
  quote?: string
}): Promise<void> {
  focusQuote.value = payload.quote ?? ''
  emit('update:collapsed', false)
  query.value = ''
  hits.value = []
  if (detail.value?.fileId !== payload.fileId) await openMaterial(payload.fileId, payload.chunkId)
  else {
    focusChunk.value = payload.chunkId
    await locate(payload.chunkId)
  }
}

watch(
  () => props.courseId,
  () => {
    detail.value = null
    chunks.value = []
    hits.value = []
    query.value = ''
    focusChunk.value = ''
    void load()
  },
  { immediate: true },
)

defineExpose({
  /** 开抽屉并翻到某一段原文（溯源徽标点的就是这个）。 */
  focusSource,
  /** 拖到工作台任意位置的文件也走这里。 */
  upload,
})
</script>

<template>
  <aside class="drawer" :class="{ 'is-collapsed': collapsed }" @dragover.prevent @drop.prevent="onDrop">
    <button v-if="collapsed" class="drawer__rail" title="展开材料抽屉" @click="emit('update:collapsed', false)">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
        <path d="M4 6.5A1.5 1.5 0 0 1 5.5 5h13A1.5 1.5 0 0 1 20 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5v-11Z" />
        <path d="M8 5v14M12 9h4M12 13h4" />
      </svg>
      <span class="drawer__rail-text">材料</span>
      <t-tag v-if="materials.length" size="small" variant="light">{{ materials.length }}</t-tag>
    </button>

    <template v-else>
      <header class="drawer__head">
        <h3>材料</h3>
        <span v-if="parsing" class="text-placeholder head-hint">{{ parsing }} 份解析中</span>
        <span class="spacer" />
        <t-button size="small" variant="outline" :loading="uploading" @click="fileEl?.click()">
          上传
        </t-button>
        <button class="drawer__fold" title="收起" @click="emit('update:collapsed', true)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
      </header>

      <input ref="fileEl" type="file" multiple hidden :accept="ACCEPT" @change="onPick" />

      <div class="drawer__body">
        <!-- 拖拽上传 -->
        <div class="drop" @click="fileEl?.click()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M12 16V4m0 0L8 8m4-4 4 4" />
            <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
          </svg>
          <span v-if="uploading">正在上传「{{ uploadingName }}」…</span>
          <span v-else>拖文件到这里，或点击选择</span>
          <span class="drop__hint">支持 md / txt / pdf / docx / pptx，单个 ≤ 50MB</span>
        </div>

        <p v-if="error" class="drawer__error" :class="{ 'is-net': errorIsNetwork }">{{ error }}</p>

        <!-- 检索 -->
        <t-input v-model="query" size="small" clearable placeholder="搜材料里的原文，例如：倒排索引" />
        <div v-if="query.trim()" class="hits">
          <p v-if="searching" class="text-placeholder hits__hint">正在检索…</p>
          <p v-else-if="!hits.length" class="text-placeholder hits__hint">没找到相关片段</p>
          <button v-for="hit in hits" :key="hit.chunkId" class="hit" @click="focusSource({ fileId: hit.fileId, chunkId: hit.chunkId, page: hit.page })">
            <span class="hit__head">
              <span class="hit__name">{{ hit.fileName }}</span>
              <span v-if="hit.page" class="text-placeholder">第 {{ hit.page }} 页</span>
              <span class="spacer" />
              <span class="mono hit__score">{{ hit.score.toFixed(2) }}</span>
            </span>
            <!-- eslint-disable-next-line vue/no-v-html -- highlight() 先转义再插 <mark>，见它的注释 -->
            <span class="hit__text" v-html="highlight(hitQuote(hit), hit.matched[0] ?? '')" />
          </button>
        </div>

        <!-- 材料列表 -->
        <div v-else class="list">
          <!-- 这门课用了哪几份：只列已加入的那些（F4-14） -->
          <button
            v-if="materials.length"
            class="list__filter"
            :class="{ 'is-on': onlyAttached }"
            @click="onlyAttached = !onlyAttached"
          >
            {{ onlyAttached ? `已加入这门课（${attachedIds.length}）` : `全部材料（${materials.length}）` }}
          </button>
          <p v-if="loading && !materials.length" class="text-placeholder hits__hint">正在读取材料…</p>
          <t-empty
            v-else-if="!materials.length"
            size="small"
            title="还没有材料"
            description="传一份讲义，生成这门课的时候就会按它来写。"
          />
          <p v-else-if="!shown.length" class="text-placeholder hits__hint">
            这门课还没有关联任何材料，点下面「全部材料」挑一份加进来。
          </p>
          <div
            v-for="item in shown"
            :key="item.fileId"
            class="mat"
            :class="{ 'is-on': detail?.fileId === item.fileId }"
            @click="openMaterial(item.fileId)"
          >
            <span class="mat__name" :title="item.name">{{ item.name }}</span>
            <t-tag v-if="attachedSet.has(item.fileId)" size="small" theme="primary" variant="light">已加入</t-tag>
            <span class="spacer" />
            <t-tag v-if="item.status === 'parsing'" size="small" theme="warning" variant="light">解析中</t-tag>
            <t-tag v-else-if="item.status === 'failed'" size="small" theme="danger" variant="light">失败</t-tag>
            <span class="text-placeholder mat__meta mono">
              <template v-if="item.status === 'ready'">{{ item.pages ? `${item.pages}页 · ` : '' }}{{ item.chunkCount }} 块</template>
            </span>
            <button
              class="mat__act"
              :title="attachedSet.has(item.fileId) ? '从这门课移除' : '加入这门课'"
              @click.stop="attachedSet.has(item.fileId) ? detach(item.fileId) : attach(item.fileId)"
            >
              {{ attachedSet.has(item.fileId) ? '移除' : '加入' }}
            </button>
            <button class="mat__act is-danger" title="删除这份材料" @click.stop="remove(item.fileId)">×</button>
          </div>
        </div>

        <!-- 预览：目录树 + 分块 -->
        <div v-if="detail" class="preview">
          <div class="preview__head">
            <span class="preview__name" :title="detail.name">{{ detail.name }}</span>
            <span class="text-placeholder">
              {{ detail.charCount }} 字 · {{ detail.chunkCount }} 块
              <template v-if="detail.pages"> · {{ detail.pages }} 页</template>
            </span>
            <button class="mat__act" @click="detail = null">收起</button>
          </div>

          <p v-if="detail.oversized" class="drawer__warn">
            这份材料很长（超过服务端的单次预算），生成时按章检索；建议拆成几份更准。
          </p>
          <p v-if="detail.status === 'parsing'" class="text-placeholder hits__hint">
            还在解析（已识别 {{ detail.charCount }} 字）…
          </p>
          <p v-else-if="detail.status === 'failed'" class="drawer__error">{{ detail.error }}</p>

          <div v-if="detail.tree.length" class="tree">
            <button
              v-for="node in detail.tree"
              :key="node.path"
              class="tree__node"
              @click="query = node.title"
            >
              <span class="tree__title">{{ node.title }}</span>
              <span class="text-placeholder">{{ node.chunkCount }} 块</span>
            </button>
          </div>

          <div
            v-for="chunk in chunks"
            :id="`chunk-${chunk.chunkId}`"
            :key="chunk.chunkId"
            class="chunk"
            :class="{ 'is-focus': chunk.chunkId === focusChunk }"
          >
            <div class="chunk__head">
              <span class="mono text-placeholder">#{{ chunk.chunkNo }}</span>
              <span v-if="chunk.pageFrom" class="text-placeholder">
                第 {{ chunk.pageFrom }}<template v-if="chunk.pageTo && chunk.pageTo !== chunk.pageFrom">–{{ chunk.pageTo }}</template> 页
              </span>
              <span v-if="chunk.sectionPath" class="chunk__section" :title="chunk.sectionPath">
                {{ chunk.sectionPath }}
              </span>
            </div>
            <!-- eslint-disable-next-line vue/no-v-html -- 同上：原文与引文都先转义 -->
            <p class="chunk__text" v-html="bodyOf(chunk)" />
          </div>

          <t-button v-if="hasMoreChunks" size="small" variant="text" block @click="moreChunks">
            继续往下看（已看 {{ chunks.length }} / {{ chunkTotal }}）
          </t-button>
        </div>
      </div>
    </template>
  </aside>
</template>
<style scoped src="../../styles/components/workbench/MaterialDrawer.css"></style>
