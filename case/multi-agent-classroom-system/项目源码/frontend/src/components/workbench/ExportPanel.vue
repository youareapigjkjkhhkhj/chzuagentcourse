<script setup lang="ts">
/**
 * 导出面板（P5-F5-1~F5-6）：选格式 → 建任务 → 看进度 → 下载，外加一份导出历史。
 *
 * 三个地方是**服务端说了算**，界面只是照做：
 *
 * 1. **有哪些格式可选**（`supported`）。课件导不了 `md`、课堂记录导不了 `pptx`，
 *    这不是界面的规矩，是渲染器的本事 —— 写死一份在前端，迟早会提供一个
 *    点了报 40001 的选项。
 * 2. **能不能下载**（`downloadable`）。「渲染完了」与「文件还在」是两件事
 *    （产物 24 小时后被清理）。前端拼 `status === 'done'` 会在文件已经被删掉时
 *    仍然亮着下载按钮。
 * 3. **链接**。带一次性票据，点下载时现取一张新的，见 `useExports.download`。
 *
 * 「重试」不是把失败那一行改活，而是**再导一次**（同样格式、同样选项）：
 * 一行 = 一次导出，失败那行留着，它记着那次为什么没成。
 */
import { computed, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

import { useExports } from '@/composables/useExports'
import { describeError } from '@/stores/settings'
import type { ExportFormat, ExportItem, ExportOptions, ExportScope } from '@/types/api'
import { EXPORT_FORMAT_LABELS, EXPORT_STATUS_LABELS, EXPORT_STATUS_THEMES } from '@/utils/labels'

const props = withDefaults(
  defineProps<{
    visible: boolean
    courseId: string
    /** 导整门课（课件）还是某一节课堂的记录（F5-5）。 */
    scope?: ExportScope
    /** `scope='record'` 时必填：导的是哪一节课堂。 */
    sessionId?: string
    /**
     * 课程级模板（首页开始生成时选的那个）。
     *
     * 面板一开就把它预选上，用户仍可在这里单次换一个 —— 课程级只是默认值，
     * 不是锁死。空字符串表示这门课没带模板（老课程），那就留在 `default`。
     */
    defaultTemplate?: string
  }>(),
  { scope: 'course', sessionId: '', defaultTemplate: '' },
)

const emit = defineEmits<{ 'update:visible': [visible: boolean] }>()

const fmt = ref<ExportFormat>('pptx')
const options = ref<Required<ExportOptions>>({
  watermark: true,
  withNotes: true,
  withQuiz: true,
  template: 'default',
})
const creating = ref(false)
/** 正在下载的那一行（按钮转圈用），一次只可能有一个。 */
const downloading = ref('')

const courseId = computed(() => props.courseId)
const { items, supported, templates, loading, error, load, create, retry, remove, download } =
  useExports(courseId)

const isRecord = computed(() => props.scope === 'record')
const header = computed(() => (isRecord.value ? '导出课堂记录' : '导出课件'))

/** 这个范围支持的格式。读不到时给个空的 —— 一个选不出来的下拉比一份猜的表强。 */
const formats = computed<ExportFormat[]>(() => supported.value[props.scope] ?? [])

/** 格式的选项文案。认得的写全称，不认得的原样显示（后端加了新格式也不空一块）。 */
function formatLabel(format: ExportFormat): string {
  return EXPORT_FORMAT_LABELS[format] ?? format
}

/** 打开时重新拉一次：上一次开着面板导的那几份，现在可能已经好了。 */
watch(
  () => props.visible,
  (visible) => {
    if (!visible || !props.courseId) return
    void load().then(pickDefault)
  },
  { immediate: true },
)

/**
 * 选一个默认格式。**从服务端给的那份里挑第一个**，而不是写死 `pptx` ——
 * 课堂记录那条路根本没有 pptx，写死的话每次打开都是一个空选中。
 *
 * 顺带把课程级模板预选上（`defaultTemplate`）：它是清单里认得的 key 才改，
 * 认不出就留在当前值，不往选择器里硬塞一个后端会 40001 的项。
 */
function pickDefault(): void {
  if (!formats.value.length) return
  if (!formats.value.includes(fmt.value)) fmt.value = formats.value[0]
  const key = props.defaultTemplate
  if (key && templates.value.some((one) => one.key === key)) options.value.template = key
}

async function submit(): Promise<void> {
  creating.value = true
  try {
    await create({
      format: fmt.value,
      scope: props.scope,
      sessionId: props.sessionId || undefined,
      // 课堂记录没有水印/讲稿那几个开关（`GET /courses/{id}/exports` 的
      // `supported` 只说了格式，没说选项），所以只有课件那条路带上它们。
      options: isRecord.value ? undefined : { ...options.value },
    })
    MessagePlugin.success('已开始导出，渲染完就能下载')
  } catch (err) {
    MessagePlugin.error(describeError(err))
  } finally {
    creating.value = false
  }
}

async function onDownload(row: ExportItem): Promise<void> {
  downloading.value = row.exportId
  try {
    await download(row.exportId)
  } catch (err) {
    // 票据是一次性的、也有十分钟的寿命：过期、被清理、刚被删掉都会走到这里。
    // 提示后重拉一次，让界面上的状态回到服务端那一份（那一行可能已经没了）。
    MessagePlugin.error(describeError(err))
    void load()
  } finally {
    downloading.value = ''
  }
}

async function onRemove(row: ExportItem): Promise<void> {
  try {
    await remove(row.exportId)
    MessagePlugin.success('已删除这次导出')
  } catch (err) {
    // 正在跑的那一次删不掉（40902）：服务端说得清原因，照原话说给用户
    MessagePlugin.error(describeError(err))
    void load()
  }
}

async function onRetry(row: ExportItem): Promise<void> {
  try {
    await retry(row)
    MessagePlugin.info('已用同样的设置重新导出一次')
  } catch (err) {
    MessagePlugin.error(describeError(err))
  }
}

/** 产物大小 → 「1.2 MB」。0 表示还没渲染出东西，给空串。 */
function sizeText(bytes: number): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 剩余有效期。产物只留 24 小时，快到期了要让人看见（P5-A6）。 */
function expiryText(row: ExportItem): string {
  const at = Date.parse(row.expiresAt)
  if (!row.expiresAt || Number.isNaN(at)) return ''
  const hours = Math.floor((at - Date.now()) / 3_600_000)
  if (hours <= 0) return '即将过期'
  if (hours < 1) return '不到 1 小时后过期'
  return `${hours} 小时后过期`
}

const busy = (row: ExportItem) => row.status === 'queued' || row.status === 'running'
</script>

<template>
  <t-dialog
    :visible="visible"
    attach="body"
    :header="header"
    :footer="false"
    width="560px"
    @update:visible="emit('update:visible', $event)"
  >
    <div class="ex-form">
      <div class="ex-row">
        <span class="ex-label">格式</span>
        <t-radio-group v-model="fmt" variant="default-filled" size="small">
          <t-radio-button v-for="one in formats" :key="one" :value="one">
            {{ formatLabel(one) }}
          </t-radio-button>
        </t-radio-group>
      </div>

      <!-- PPT 模板（配色+字体）：清单由后端下发，只对课件生效（课堂记录不套模板） -->
      <div v-if="!isRecord && templates.length" class="ex-row">
        <span class="ex-label">模板</span>
        <t-select v-model="options.template" size="small" class="ex-select">
          <t-option v-for="one in templates" :key="one.key" :value="one.key" :label="one.name" />
        </t-select>
      </div>

      <!-- 课堂记录是一份逐字稿，没有水印与备注页那回事（F5-5） -->
      <div v-if="!isRecord" class="ex-row">
        <span class="ex-label">选项</span>
        <div class="ex-switches">
          <label><t-switch v-model="options.watermark" size="small" /> 加页码水印</label>
          <label><t-switch v-model="options.withNotes" size="small" /> 讲稿进备注页</label>
          <label><t-switch v-model="options.withQuiz" size="small" /> 含测验与答案</label>
        </div>
      </div>

      <p v-if="!formats.length" class="ex-empty">这门课还没有可用的导出格式。</p>
      <t-button v-else theme="primary" size="small" :loading="creating" @click="submit">
        开始导出
      </t-button>
    </div>

    <h4 class="ex-title">导出历史</h4>
    <p v-if="loading && !items.length" class="ex-empty">读取中…</p>
    <p v-else-if="error" class="ex-empty is-error">{{ error }}</p>
    <p v-else-if="!items.length" class="ex-empty">还没有导出过。</p>

    <div v-for="row in items" :key="row.exportId" class="ex-item">
      <div class="ex-item__head">
        <t-tag size="small" variant="light" :theme="EXPORT_STATUS_THEMES[row.status]">
          {{ EXPORT_STATUS_LABELS[row.status] }}
        </t-tag>
        <span class="ex-item__name">{{ formatLabel(row.format) }}</span>
        <span class="ex-item__meta mono">
          {{ sizeText(row.sizeBytes) }}
          <template v-if="row.status === 'done'">· {{ expiryText(row) }}</template>
        </span>
      </div>

      <div v-if="busy(row)" class="ex-item__bar">
        <t-progress :percentage="row.progress" :label="false" theme="line" size="small" />
        <span class="mono">{{ row.progress }}%</span>
      </div>

      <p v-if="row.error" class="ex-item__error">{{ row.error }}</p>

      <div class="ex-item__acts">
        <t-button
          v-if="row.downloadable"
          size="small"
          theme="primary"
          variant="outline"
          :loading="downloading === row.exportId"
          @click="onDownload(row)"
        >
          下载
        </t-button>
        <t-button v-if="row.status === 'failed'" size="small" variant="outline" @click="onRetry(row)">
          重试
        </t-button>
        <t-button
          v-if="!busy(row)"
          size="small"
          variant="text"
          theme="danger"
          @click="onRemove(row)"
        >
          删除
        </t-button>
      </div>
    </div>

    <p class="ex-note">
      产物保存在服务器上 24 小时，过期后自动清理；下载链接是一次性的，每次点都会重新签一张。
      <template v-if="isRecord">课堂记录导出的是那一节课的逐字稿与板书快照。</template>
    </p>
  </t-dialog>
</template>

<style scoped>
.ex-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--td-component-stroke);
}

.ex-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.ex-label {
  width: 34px;
  flex-shrink: 0;
  padding-top: 4px;
  font-size: 13px;
  color: var(--td-text-secondary);
}

.ex-switches {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  font-size: 13px;
}

.ex-select {
  flex: 1;
}

.ex-switches label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.ex-title {
  margin: 14px 0 8px;
  font-size: 13px;
  font-weight: 600;
}

.ex-empty {
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.ex-empty.is-error {
  color: var(--td-error-color);
}

.ex-item {
  padding: 8px 0;
  border-bottom: 1px dashed var(--td-component-stroke);
}

.ex-item__head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.ex-item__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ex-item__meta {
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.ex-item__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.ex-item__bar :deep(.t-progress) {
  flex: 1;
}

.ex-item__error {
  margin-top: 6px;
  font-size: 12px;
  color: var(--td-error-color);
}

.ex-item__acts {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.ex-note {
  margin-top: 12px;
  font-size: 11px;
  line-height: 1.8;
  color: var(--td-text-placeholder);
}

.mono {
  font-family: var(--td-font-mono);
}
</style>
