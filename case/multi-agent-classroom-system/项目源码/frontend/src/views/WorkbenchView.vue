<script setup lang="ts">
/**
 * 工作台（P1-A3 / A4 / A7~A11 / B5，P4 §6）—— 版式照 `产品原型/workbench.html`。
 *
 * 两列 + 一个浮框：左 = **课程大纲**，中 = 页面编辑（预览 + 可收缩的页面属性），
 * 右下角 = 生成任务 / 对话 / 材料（`AgentFloat`，可收起）。
 *
 * 会话原来在左栏，与大纲树挤一块地方：两样都要高度，两样都看不全。材料抽屉
 * 原来单独占一个 340px 的右栏，把中间那格挤到幻灯片只有 840px 宽。现在按
 * 「**要一直看着的**（大纲、预览）留在栏里，**有事才看的**（进度、对话、材料）
 * 收进浮框」分开 —— 生成跑完把浮框一收，中间那块预览就全露出来了。
 *
 * 这一版把 P1 的「左任务 / 中大纲 / 右预览」重排成 P4 的顺序，理由是
 * **说话的地方要挨着被改的东西**：改页面时说的时候选中了哪一页
 * （`refPageNo`）已经捎上去了，页面就在中间那一栏。
 *
 * 三条规矩贯穿全篇：
 *
 * 1. **界面上的每个数字都得能追到一次响应或一帧事件**（P1-B5）。进度、步骤、
 *    正在写第几页全走 `useGenerationStream`（SSE 为主、REST 兜底）；大纲树的
 *    四态里三个来自 `GET /outline`，「生成中」由 SSE 的实时页号补上。
 * 2. **前端只在本地维护一件事：用户把这棵树改成了什么样**（`useOutlineDraft`）。
 *    提交给服务端的是这棵树本身 —— 页号、状态、页数的重排是服务端的活。
 * 3. **Agent 改过的页面要当场看见**。`page.rewritten` 到了就重读那一页与大纲，
 *    P4-A9 的「大纲树同步更新」说的就是这条：不刷新就等于让用户对着旧内容。
 *
 * 增删改序全部**只在「大纲确认点」开着**（`tree.confirmable`）：生成跑起来之后
 * 服务端一律 409，那时候还能删页就是个陷阱（删了没处提交）。
 */
import { computed, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useRoute, useRouter } from 'vue-router'

import AgentFloat from '@/components/workbench/AgentFloat.vue'
import ExportPanel from '@/components/workbench/ExportPanel.vue'
import OutlineAddDialog from '@/components/workbench/OutlineAddDialog.vue'
import OutlinePanel from '@/components/workbench/OutlinePanel.vue'
import OutlineTree from '@/components/workbench/OutlineTree.vue'
import PageEditor from '@/components/workbench/PageEditor.vue'
import PageSlide from '@/components/workbench/PageSlide.vue'
import { useGenerationStream } from '@/composables/useGenerationStream'
import { useOutlineDraft } from '@/composables/useOutlineDraft'
import type { PageRewrite } from '@/composables/useWorkbenchChat'
import * as api from '@/api'
import { describeError, useSettingsStore } from '@/stores/settings'
import { COURSE_STATUS_LABELS } from '@/utils/labels'
import type { CoursePageItem, OutlineTree as OutlineTreeData, SlideSource } from '@/types/api'

const route = useRoute()
const router = useRouter()
const settings = useSettingsStore()

/** 课程与任务都写在地址栏上（首页点进来时带上），刷新页面还能回到同一门课。 */
const courseId = computed(() => String(route.query.course ?? '').trim())
const jobId = computed(() => String(route.query.job ?? '').trim())

const tree = ref<OutlineTreeData | null>(null)
const page = ref<CoursePageItem | null>(null)
const selectedNo = ref(0)
const confirming = ref(false)
/** 用户点过「取消」。任务状态以后端为准，这个只记「这一下是我按的」。 */
const canceled = ref(false)
const loadError = ref('')

/** 导出面板开不开（P5-F5-6）。 */
const exportVisible = ref(false)

/**
 * 右下角那个浮框。材料抽屉现在住它里面（「材料」页签），所以「展开抽屉、
 * 翻到某一段原文、传一个文件」这几件事都得绕它一手 —— 见 `onOpenSource`
 * 与 `onWorkspaceDrop`。
 */
const floatEl = ref<InstanceType<typeof AgentFloat> | null>(null)
/** 材料里正显示着的那条出处（`materialId:chunkId`），徽标据此高亮。 */
const activeSource = ref('')
/** 原文已经取不到的出处（材料删了）：徽标画成失效态（P4-A13）。 */
const missingSources = ref<string[]>([])

/** 删页、加页、加章、拖动都只动这份草稿，点「确认大纲」才整棵提交（P1-A3）。 */
const { dirty, addChapter, addPage, markClean, movePage, removePage, toSubmit } =
  useOutlineDraft(tree)

/** 增章 / 增页都先问名字：标题会进写页的提示词，落到树上再改就晚了。 */
const addVisible = ref(false)
const addMode = ref<'chapter' | 'page'>('chapter')
const addChapterNo = ref(0)

const addContext = computed(() => {
  const chapter = tree.value?.chapters.find((item) => item.no === addChapterNo.value)
  return chapter ? `「${chapter.title}」` : '这一章'
})

function openAddChapter(): void {
  if (!tree.value) return
  addMode.value = 'chapter'
  addVisible.value = true
}

function openAddPage(chapterNo: number): void {
  addMode.value = 'page'
  addChapterNo.value = chapterNo
  addVisible.value = true
}

function onAdd(payload: { chapterTitle: string; pageTitle: string }): void {
  const added =
    addMode.value === 'chapter'
      ? addChapter(payload.chapterTitle, payload.pageTitle)
      : addPage(addChapterNo.value, payload.pageTitle)
  addVisible.value = false
  if (added) MessagePlugin.success('已加到大纲，点「确认大纲」才会提交')
}

const {
  steps,
  batches,
  percent,
  status,
  error: streamError,
  resumable,
  livePageNo,
  readyPages,
  connected: streamConnected,
  mode: streamMode,
  refresh: refreshJob,
} = useGenerationStream(jobId)

const outlinePages = computed(() => {
  const current = tree.value
  if (!current) return 0
  return current.front.length + current.chapters.length + current.back.length
})

/** 折叠块标题上那行小字：页数照抄大纲接口，不自己数。 */
const outlineSummary = computed(() =>
  tree.value ? `${tree.value.pageCount} 页` : courseId.value ? '读取中…' : '',
)

/** 左栏顶上那行「谁在服务」：课程、状态、页数都照抄大纲接口，不写死「已连接」。 */
const sessionLine = computed(() => {
  const current = tree.value
  if (!current) return courseId.value ? '正在读取这门课…' : '还没有选择课程'
  const bits = [current.title, COURSE_STATUS_LABELS[current.status]]
  if (current.pageCount) bits.push(`${current.pageCount} 页`)
  return bits.join(' · ')
})

/**
 * 进度是自己推来的还是回问来的，如实写在卡片下面。
 *
 * 用户不需要知道 SSE 是什么，但「数字是活的」和「数字刚断过」是两件事 ——
 * 后者要能解释「为什么半天没动」。
 */
const linkLine = computed(() => {
  if (streamMode.value === 'polling') return '实时推送断过，正在每 3 秒回问一次进度'
  return streamConnected.value ? '进度来自生成任务的实时推送' : '实时推送未连接'
})

async function loadOutline(): Promise<void> {
  const id = courseId.value
  if (!id) {
    tree.value = null
    return
  }
  try {
    tree.value = await api.fetchOutline(id)
    loadError.value = ''
  } catch (error) {
    // 拉不到就留着上一次那棵树：一次网络抖动不该把屏幕擦空
    loadError.value = describeError(error)
    MessagePlugin.error(loadError.value)
  }
}

/**
 * 材料开关（P4-G3）：`MATERIAL_ENABLED=false` 的部署里，右栏整块不出现。
 *
 * 只问这一次，失败就按「开着」算（`settings.materialEnabled` 里说明了理由）——
 * 工作台本来就有一堆别的请求要发，不能为了一个开关把首屏卡住。
 */
void settings.loadCapabilities().catch(() => {})

/** 切课程：连选择一起清掉，别让上一门课的页号留在右边。 */
watch(
  courseId,
  () => {
    tree.value = null
    page.value = null
    selectedNo.value = 0
    loadError.value = ''
    activeSource.value = ''
    missingSources.value = []
    markClean() // 上一门课没提交的改动随它去，别记到这一门头上
    if (courseId.value) void loadOutline()
  },
  { immediate: true },
)

// 换任务就重新开始记「取消」：新任务当然还没被取消
watch(jobId, () => {
  canceled.value = false
})

/**
 * 任务状态一变就重问一次大纲。
 *
 * 「等确认大纲」是服务端在 `confirmable` 上说的，写完一页是哪一页的状态、
 * 收尾后页数是多少，也都在那份响应里 —— 与其让前端跟着帧猜，不如重问一次。
 *
 * **本地有没提交的改动时先不重问**：那会把用户刚删掉的页原样还回来，
 * 而他多半正打算点「确认大纲」。提交成功后由 `confirm()` 自己重问一次。
 */
watch(status, (value, previous) => {
  if (value && value !== previous && !dirty.value) void loadOutline()
})

/**
 * 打开一页。
 *
 * **点的是当前这一页就不重读**：重读会把右侧没保存的草稿连同 `rev` 一起
 * 冲掉，用户只是点了一下自己正在改的那页而已。
 */
async function select(pageNo: number): Promise<void> {
  const id = courseId.value
  if (!id || pageNo === selectedNo.value) return
  selectedNo.value = pageNo
  try {
    page.value = await api.fetchPage(id, pageNo)
  } catch (error) {
    page.value = null
    MessagePlugin.error(describeError(error))
  }
}

/** 删一页。删的正好是右边开着的那页时，连预览一起清掉 ——
 *  别让人对着一个已经不在大纲里的页面继续改。 */
function onRemovePage(payload: { chapterNo: number; pageNo: number }): void {
  removePage(payload)
  if (selectedNo.value === payload.pageNo) {
    selectedNo.value = 0
    page.value = null
  }
}

/** 丢掉本地改动，回到服务端那一版。 */
async function revertDraft(): Promise<void> {
  await loadOutline()
  markClean()
  MessagePlugin.info('已还原成服务端那一版')
}

/**
 * 提交确认后的大纲（A3）。
 *
 * 交回去的是屏幕上这棵树：封面、大纲页、测验页这些由管线按规则补齐的页
 * 也一起交 —— 服务端会先把它们摘掉再补一遍，前端不替它算这一遍。
 * 页被删光的章节整章不交（`useOutlineDraft.toSubmit`）：一章没有正文可讲，
 * 交上去也会被拒。
 */
async function confirm(): Promise<void> {
  const id = courseId.value
  const outline = toSubmit()
  if (!id || !outline) return
  if (!outline.chapters.length) {
    MessagePlugin.warning('至少要留一章再提交')
    return
  }

  confirming.value = true
  try {
    await api.confirmOutline(id, outline)
    markClean()
    MessagePlugin.success('大纲已提交，继续写页面')
    await loadOutline() // 页号与页数是服务端重排的，重问一次拿新的
  } catch (error) {
    MessagePlugin.error(describeError(error))
  } finally {
    confirming.value = false
  }
}

async function cancel(): Promise<void> {
  const id = jobId.value
  if (!id) return
  try {
    await api.cancelJob(id)
    canceled.value = true
    MessagePlugin.info('已取消生成，写好的页面留在课程里')
  } catch (error) {
    MessagePlugin.error(describeError(error))
  }
}

async function retry(stepId: string): Promise<void> {
  const id = jobId.value
  if (!id) return
  try {
    await api.retryStep(id, stepId)
    MessagePlugin.info('已重新排队这一步')
    refreshJob() // 重试之后服务端不一定马上发帧，先回问一次
  } catch (error) {
    MessagePlugin.error(describeError(error))
  }
}

/**
 * 断点续跑（P5-F5-9）：从第一个没做完的步骤接着跑。
 *
 * 与「重试某一步」的区别对用户可见，所以两句话说的是两件事：重试是「这一页我
 * 想再来一次」，续跑是「接着上次的地方往下跑」。已经写好的页面一页都不会重写。
 *
 * 续跑会把任务推回 running，而取消标记（`canceled`）是本地的一次性记号 ——
 * 不清掉的话，「取消生成」按钮会一直不亮（`canCancel` 看它）。
 */
async function resume(): Promise<void> {
  const id = jobId.value
  if (!id) return
  try {
    await api.resumeJob(id)
    canceled.value = false
    MessagePlugin.info('已接着上次的地方继续生成')
    refreshJob() // 同上：刚提交时服务端不一定马上发帧
  } catch (error) {
    MessagePlugin.error(describeError(error))
  }
}

/** 预览课堂：P1 只做到「把生成结果按幻灯片翻一遍」，真正的课堂运行时在 P3。 */
function openClassroom(): void {
  if (!courseId.value) return
  void router.push({ name: 'classroom', query: { course: courseId.value } })
}

/* --- 与对话、材料两侧的连接 --- */

/**
 * Agent 改了某一页（`page.rewritten`）。
 *
 * 三种情况分开处理，因为它们的后果不一样：**删页**要把中间那栏清掉，
 * **改的正好是当前这一页**要重读它（否则用户盯着一份旧内容），
 * **改的是别的页**只需刷新大纲树上的状态。
 */
async function onPageRewritten(info: PageRewrite): Promise<void> {
  if (info.removed) {
    if (selectedNo.value === info.pageNo) {
      selectedNo.value = 0
      page.value = null
    }
    MessagePlugin.info(`第 ${info.pageNo} 页已被删掉`)
  } else if (info.pageNo === selectedNo.value && courseId.value) {
    try {
      page.value = await api.fetchPage(courseId.value, info.pageNo)
    } catch (error) {
      MessagePlugin.error(describeError(error))
    }
  }
  // 本地有没提交的大纲改动时先不覆盖那棵树（同 `watch(status)` 的理由）
  if (!dirty.value) await loadOutline()
}

/** 点出处徽标：浮框跳到「材料」页签、翻到那一段原文（P4-A6）。 */
async function onOpenSource(source: SlideSource): Promise<void> {
  activeSource.value = `${source.materialId}:${source.chunkId}`
  // 抽屉在浮框里是常驻的（v-show），不用再等它挂载：直接切页签再翻
  floatEl.value?.showMaterials()
  await floatEl.value?.focusMaterial({
    fileId: source.materialId,
    chunkId: source.chunkId,
    page: source.pageNo,
    quote: source.quote,
  })
}

/** 抽屉说这条出处打不开了（材料被删）：徽标从此画成失效态。 */
function onMissingSource(key: string): void {
  if (!missingSources.value.includes(key)) missingSources.value = [...missingSources.value, key]
}

/** 拖到工作台任意位置都能传（P4 §6）：把浮框切到「材料」页签，再转交给抽屉。 */
function onWorkspaceDrop(event: DragEvent): void {
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (!files.length) return
  floatEl.value?.showMaterials()
  floatEl.value?.uploadFiles(files)
}
</script>

<template>
  <div class="wb" @dragover.prevent @drop.prevent="onWorkspaceDrop">
    <!-- 左：课程大纲。会话与生成任务在右下角的浮框里（AgentFloat） -->
    <OutlinePanel
      :session-line="sessionLine"
      :outline-summary="outlineSummary"
      :outline-dirty="dirty"
    >
      <div class="wb-outline__head">
        <t-button
          v-if="tree?.confirmable"
          class="wb-confirm"
          size="small"
          theme="primary"
          :loading="confirming"
          @click="confirm"
        >
          确认大纲
        </t-button>
        <t-button
          v-if="tree"
          size="small"
          variant="dashed"
          :disabled="!tree.confirmable"
          @click="openAddChapter"
        >
          <template #icon>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </template>
          章节
        </t-button>
        <span class="spacer" />
        <t-button v-if="dirty" size="small" variant="text" @click="revertDraft">还原</t-button>
      </div>

      <OutlineTree
        v-if="tree && outlinePages"
        :tree="tree"
        :selected-no="selectedNo"
        :live-page-no="livePageNo"
        :ready-pages="readyPages"
        :editable="tree.confirmable"
        @select="select"
        @remove="onRemovePage"
        @add-page="openAddPage"
        @move="movePage"
      />
      <div v-else class="wb-tree-empty">
        <t-empty
          v-if="tree"
          size="small"
          title="大纲还没生成"
          description="大纲出来之后，章节与页面会出现在这里，可以删页、加页、拖动调序，改完点「确认大纲」。"
        />
        <t-empty
          v-else
          size="small"
          :title="loadError ? '大纲没拉下来' : '还没有选择课程'"
          :description="loadError || '从首页输入一个主题开始生成，或者打开一门最近课堂。'"
        />
      </div>
    </OutlinePanel>

    <!-- 中：预览与属性 -->
    <section class="wb-main">
      <div class="wb-toolbar">
        <h3>页面编辑</h3>
        <t-tag v-if="page" theme="primary" variant="light">第 {{ page.pageNo }} 页</t-tag>
        <t-tag v-if="page" class="page-rev" variant="light">rev {{ page.rev }}</t-tag>
        <span class="spacer" />
        <!--
          导出入口不自己判「这门课能不能导」（P5-F5-6）：判据是「有就绪的页
          且 dsl 里有正文」，那是服务端两份数据的事。点下去被挡回来时，
          服务端给的那句话（「这门课还没有生成好的页面，先生成完再导出」）
          比一个没有理由的灰按钮有用。
        -->
        <t-button :disabled="!courseId" @click="exportVisible = true">导出课件</t-button>
        <t-button :disabled="!courseId" @click="openClassroom">预览课堂</t-button>
      </div>

      <div class="wb-main__body">
        <PageSlide
          :page="page"
          :course-title="tree?.title ?? ''"
          :page-count="tree?.pageCount ?? 0"
          :active-source="activeSource"
          :missing-sources="missingSources"
          @open-source="onOpenSource"
        />
        <PageEditor
          v-if="page"
          :course-id="courseId"
          :page="page"
          @saved="page = $event"
          @rewritten="page = $event"
        />
      </div>
    </section>

    <!--
      右栏没了：材料抽屉搬进了右下角那个浮框的「材料」页签（AgentFloat）。
      原来中间那格被 340px 的抽屉挤成一条，幻灯片只有 840px 宽 —— 16:9 的
      课件在那个尺寸上根本看不清。现在宽度整个还给预览。
    -->

    <OutlineAddDialog
      v-model:visible="addVisible"
      :mode="addMode"
      :context="addContext"
      :chapter-count="tree?.chapters.length ?? 0"
      @confirm="onAdd"
    />

    <!-- scope 缺省是 course：工作台导的是整门课的课件 -->
    <ExportPanel v-model:visible="exportVisible" :course-id="courseId" />

    <!--
      右下角：生成任务 + 对话 + 材料。挂在工作台上而不是某一栏里 ——
      它是浮的，左中两栏怎么排都不影响它。
    -->
    <AgentFloat
      ref="floatEl"
      :course-id="courseId"
      :materials-enabled="settings.materialEnabled"
      :ref-page-no="selectedNo"
      :job-id="jobId"
      :steps="steps"
      :batches="batches"
      :percent="percent"
      :status="status"
      :canceled="canceled"
      :error="streamError"
      :resumable="resumable"
      :link-line="linkLine"
      @cancel="cancel"
      @retry="retry"
      @resume="resume"
      @page-rewritten="onPageRewritten"
      @select-page="select"
      @open-source="onOpenSource"
      @missing="onMissingSource"
    />
  </div>
</template>

<style scoped>
/* 骨架取自 产品原型/workbench.html，但右栏（材料）已经并进右下角的浮框 */
.wb {
  display: flex;
  height: calc(100vh - 60px);
  overflow: hidden;
}

/* 左栏（大纲）的宽度跟着组件自己走 —— 那一栏的版式，连同 `flex-shrink: 0`
   的定宽，都在 `OutlinePanel` 里。 */

.wb-outline__head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
}

.wb-outline__head .spacer {
  flex: 1;
}

.wb-tree-empty {
  padding: 16px;
  display: flex;
  justify-content: center;
}

/* --- 中：预览 + 属性 --- */

.wb-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--td-bg-page);
}

.wb-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px;
  background: var(--td-bg-container);
  border-bottom: 1px solid var(--td-component-stroke);
}

.wb-toolbar h3 {
  font-size: 15px;
  font-weight: 600;
  margin-right: 8px;
}

.wb-toolbar .spacer {
  flex: 1;
}

.wb-main__body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  gap: 20px;
  align-items: flex-start;
  /*
   * **别在这儿加 `justify-content: space-between`**：预览铺满时它没作用，
   * 可一旦高度上限生效（矮屏）预览缩了，它就把属性栏推到最右边，中间空出
   * 一大块 —— 看着就是「PPT 右边有空白」。空出来的地方交给行尾才对。
   */
}
</style>
