<script setup lang="ts">
/**
 * 工作台（P1-A3 / A4 / A7 / A8 / A9 / A11 / B5）—— 版式照 `产品原型/workbench.html`。
 *
 * 三列：左 = 生成任务卡（六步 + 总进度），中 = 大纲树（可删页、可加页、可拖序、
 * 可确认），右 = 预览（只读）+ 页面属性（可改）。
 *
 * 一条规矩贯穿全篇：**界面上的每个数字都得能追到一次响应或一帧事件**（P1-B5）。
 * 所以进度、步骤、正在写第几页全走 `useGenerationStream`（SSE 为主、REST 兜底）；
 * 大纲树的四态里三个来自 `GET /outline`，「生成中」由 SSE 的实时页号补上。
 *
 * 前端只在本地维护一件事：**用户把这棵树改成了什么样**（`useOutlineDraft`）。
 * 提交给服务端的是这棵树本身 —— 页号、状态、页数的重排是服务端的活
 * （见 `intake.clean_outline`），前端再算一份就是同一件事的两个真相。
 *
 * 增删改序全部**只在「大纲确认点」开着**（`tree.confirmable`）：生成跑起来之后
 * 服务端一律 409（「这次生成已经结束，大纲不能再改」），那时候还能删页就是个陷阱 ——
 * 删了没处提交。所以编辑入口跟着这个开关走，而不是跟着「有没有选中一页」走。
 */
import { computed, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useRoute, useRouter } from 'vue-router'

import GenTaskPanel from '@/components/workbench/GenTaskPanel.vue'
import OutlineAddDialog from '@/components/workbench/OutlineAddDialog.vue'
import OutlineTree from '@/components/workbench/OutlineTree.vue'
import PageEditor from '@/components/workbench/PageEditor.vue'
import PageSlide from '@/components/workbench/PageSlide.vue'
import { useGenerationStream } from '@/composables/useGenerationStream'
import { useOutlineDraft } from '@/composables/useOutlineDraft'
import * as api from '@/api'
import { describeError } from '@/stores/settings'
import { COURSE_STATUS_LABELS } from '@/utils/labels'
import type { CoursePageItem, OutlineTree as OutlineTreeData } from '@/types/api'

const route = useRoute()
const router = useRouter()

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

/** 左边那行「谁在服务」：课程、状态、页数都照抄大纲接口，不写死「已连接」。 */
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

/** 切课程：连选择一起清掉，别让上一门课的页号留在右边。 */
watch(
  courseId,
  () => {
    tree.value = null
    page.value = null
    selectedNo.value = 0
    loadError.value = ''
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

/** 预览课堂：P1 只做到「把生成结果按幻灯片翻一遍」，真正的课堂运行时在 P3。 */
function openClassroom(): void {
  if (!courseId.value) return
  void router.push({ name: 'classroom', query: { course: courseId.value } })
}
</script>

<template>
  <div class="wb">
    <!-- 左：生成任务 -->
    <GenTaskPanel
      :session-line="sessionLine"
      :job-id="jobId"
      :steps="steps"
      :batches="batches"
      :percent="percent"
      :status="status"
      :canceled="canceled"
      :error="streamError"
      :link-line="linkLine"
      @cancel="cancel"
      @retry="retry"
    />

    <!-- 中：大纲树 -->
    <section class="wb-outline">
      <div class="wb-outline__head">
        <h3>课程大纲</h3>
        <span v-if="tree" class="text-placeholder head-count">{{ tree.pageCount }} 页</span>
        <span class="spacer" />
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
      </div>

      <!-- 本地改动提示条：只在真有改动时出现，说清「还没提交」并给一条退路 -->
      <div v-if="dirty" class="wb-outline__draft">
        <t-tag theme="warning" variant="light" size="small">大纲有改动未提交</t-tag>
        <span class="spacer" />
        <t-button size="small" variant="text" @click="revertDraft">还原</t-button>
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
    </section>

    <!-- 右：预览与属性 -->
    <section class="wb-main">
      <div class="wb-toolbar">
        <h3>页面编辑</h3>
        <t-tag v-if="page" theme="primary" variant="light">第 {{ page.pageNo }} 页</t-tag>
        <t-tag v-if="page" class="page-rev" variant="light">rev {{ page.rev }}</t-tag>
        <span class="spacer" />
        <t-button :disabled="!courseId" @click="openClassroom">预览课堂</t-button>
      </div>

      <div class="wb-main__body">
        <PageSlide
          :page="page"
          :course-title="tree?.title ?? ''"
          :page-count="tree?.pageCount ?? 0"
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

    <OutlineAddDialog
      v-model:visible="addVisible"
      :mode="addMode"
      :context="addContext"
      :chapter-count="tree?.chapters.length ?? 0"
      @confirm="onAdd"
    />
  </div>
</template>

<style scoped>
/* 三栏骨架取自 产品原型/workbench.html */
.wb {
  display: flex;
  height: calc(100vh - 60px);
  overflow: hidden;
}

/* 左栏（生成任务）的样式跟着 GenTaskPanel 走 —— 它自己那一栏的版式，
   连同 `--flex-shrink: 0` 的定宽，都在那个组件里。 */

/* --- 中：大纲 --- */

.wb-outline {
  width: 340px;
  flex-shrink: 0;
  background: var(--td-bg-container);
  border-right: 1px solid var(--td-component-stroke);
  display: flex;
  flex-direction: column;
}

.wb-outline__head {
  padding: 14px 16px;
  border-bottom: 1px solid var(--td-component-stroke);
  display: flex;
  align-items: center;
  gap: 8px;
}

.wb-outline__head h3 {
  font-size: 15px;
  font-weight: 600;
}

.wb-outline__head .head-count {
  font-size: 12px;
}

.wb-outline__head .spacer {
  flex: 1;
}

/* 本地改动提示条：真改了什么才出现，平时不占地方 */
.wb-outline__draft {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--td-warning-color-light);
  border-bottom: 1px solid var(--td-component-stroke);
}

.wb-outline__draft .spacer {
  flex: 1;
}

.wb-tree-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

/* --- 右：预览 + 属性 --- */

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
}
</style>
