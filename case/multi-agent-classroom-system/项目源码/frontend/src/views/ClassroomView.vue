<script setup lang="ts">
/**
 * 课堂演示：一门已生成课程的**只读预览**（真正的课堂运行时在 P3，语音在 P2）。
 *
 * 版式照 `产品原型/classroom.html`：顶栏 + 左侧舞台 + 右侧面板。
 * 原型里那些对话、字幕、幻灯片都是写死的演示内容，这里一律换成真数据 ——
 * 一页看起来很热闹但其实什么都没跑起来的课堂，比空白更误导人。
 *
 * 「按页看一门已经生成好的课」不需要课堂运行时：幻灯片、讲稿、大纲都在 P1
 * 落库了。所以这一页接的是课程库（课程号从地址栏来，刷新还在），
 * 翻不动、听不见、聊不了的那三件事照实写在提示条上。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useRoute, useRouter } from 'vue-router'

import ClassroomPanel from '@/components/classroom/ClassroomPanel.vue'
import ClassroomStage from '@/components/classroom/ClassroomStage.vue'
import * as api from '@/api'
import { describeError, useSettingsStore } from '@/stores/settings'
import type { CourseDetail, CoursePageItem, OutlineTree } from '@/types/api'

const route = useRoute()
const router = useRouter()
const settings = useSettingsStore()

/** 课程号写在地址栏上（工作台点「预览课堂」时带上），刷新回到同一门课。 */
const courseId = computed(() => String(route.query.course ?? '').trim())

const course = ref<CourseDetail | null>(null)
const outline = ref<OutlineTree | null>(null)
const pageNo = ref(0)
const loading = ref(false)
const loadError = ref('')

const pages = computed<CoursePageItem[]>(() => course.value?.pages ?? [])
const currentPage = computed(
  () => pages.value.find((item) => item.pageNo === pageNo.value) ?? null,
)
/** 整门课的页数照服务端那份（卡片上写的也是它），不是「已经拉下来几页」。 */
const pageCount = computed(() => course.value?.pageCount ?? pages.value.length)
const index = computed(() => pages.value.findIndex((item) => item.pageNo === pageNo.value))
const canPrev = computed(() => index.value > 0)
const canNext = computed(() => index.value >= 0 && index.value < pages.value.length - 1)

const teacherCount = computed(() => settings.roles.filter((r) => r.role === 'teacher').length)
const classmateCount = computed(
  () => settings.roles.filter((r) => r.role !== 'teacher').length,
)

/** 空状态三种说法：没选课 / 正在读 / 读失败 —— 别让「读失败」看起来像「课程是空的」。 */
const emptyTitle = computed(() =>
  loadError.value ? '这门课没读出来' : '还没有可讲授的课程',
)
const emptyText = computed(() => {
  if (loadError.value) return loadError.value
  if (loading.value) return '正在读取课程内容…'
  if (!courseId.value)
    return '课堂演示要有一门课：从首页打开一门已生成的课程，或者在工作台点「预览课堂」。课堂运行时（AI 教师语音授课、AI 同学讨论、举手发言）在 P3 阶段接入。'
  return '这门课还没有生成好的页面 —— 回工作台把它生成完，再回来看。'
})

async function load(id: string): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const [detail, tree] = await Promise.all([
      api.fetchCourse(id, { withPages: true }),
      api.fetchOutline(id),
    ])
    course.value = detail
    outline.value = tree
    pageNo.value = detail.pages?.[0]?.pageNo ?? 0
  } catch (error) {
    // 一次读失败不该把页面擦成白的：留个说得清的错，别静默
    course.value = null
    outline.value = null
    pageNo.value = 0
    loadError.value = describeError(error)
  } finally {
    loading.value = false
  }
}

/** 换课程就整页重来：上一门课的页号留在舞台上比空白更糟。 */
watch(
  courseId,
  (id) => {
    if (id) {
      void load(id)
      return
    }
    course.value = null
    outline.value = null
    pageNo.value = 0
    loadError.value = ''
  },
  { immediate: true },
)

/** 翻页按「已生成的页」走：翻到不存在的页只会得到一片空白。 */
function go(offset: number): void {
  const next = pages.value[index.value + offset]
  if (next) pageNo.value = next.pageNo
}

function jump(no: number): void {
  if (pages.value.some((item) => item.pageNo === no)) pageNo.value = no
}

/** 导出菜单：原型上是「导出课件」按钮弹出的四项。 */
const EXPORTS = [
  { value: 'pptx', content: '导出 PPTX' },
  { value: 'html', content: '导出 HTML' },
  { value: 'pdf', content: '导出 PDF' },
  { value: 'share', content: '分享课堂链接', divider: true },
]

function onExport(value: string) {
  const label = EXPORTS.find((item) => item.value === value)?.content ?? '导出'
  MessagePlugin.info(`${label}将在 P4 阶段接入（导出与分享）`)
}

onMounted(() => {
  void settings.loadRoles()
})
</script>

<template>
  <div class="cls">
    <header class="cls-header">
      <span class="back" title="返回首页" @click="router.push('/')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M15 5l-7 7 7 7" />
        </svg>
      </span>
      <div class="cls-header__info">
        <div class="cls-header__title">{{ course?.title ?? '课堂演示' }}</div>
        <div class="cls-header__meta">
          <t-tag v-if="!course" variant="light">尚未开课</t-tag>
          <template v-else>
            <t-tag variant="light" theme="primary">只读预览</t-tag>
            <t-tag v-if="teacherCount" variant="light">{{ teacherCount }} 位教师</t-tag>
            <t-tag v-if="classmateCount" variant="light">
              {{ classmateCount }} 位 AI 同学
            </t-tag>
          </template>
        </div>
      </div>
      <span class="spacer" />
      <t-button @click="MessagePlugin.info('举手提问随课堂运行时在 P3 接入')">
        <template #icon>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path
              d="M7 11V5.5a1.5 1.5 0 0 1 3 0V10m0-4.5v-1a1.5 1.5 0 0 1 3 0V10m0-4.5a1.5 1.5 0 0 1 3 0V12m0-3a1.5 1.5 0 0 1 3 0v5a6 6 0 0 1-6 6h-1.4a6 6 0 0 1-4.8-2.4L4 15.6a1.6 1.6 0 0 1 2.6-1.9L7 14.5"
            />
          </svg>
        </template>
        举手
      </t-button>
      <t-dropdown :options="EXPORTS" trigger="click" @click="onExport($event as string)">
        <t-button theme="primary">
          <template #icon>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M12 3v12M7 10l5 5 5-5" />
              <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
            </svg>
          </template>
          导出课件
        </t-button>
      </t-dropdown>
      <t-button shape="square" variant="outline" title="设置" @click="router.push('/settings')">
        <template #icon>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <circle cx="12" cy="12" r="3" />
            <path
              d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.51 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1Z"
            />
          </svg>
        </template>
      </t-button>
    </header>

    <div v-if="course" class="cls-banner">
      <t-alert theme="info">
        <template #message>
          这是生成结果的只读预览：翻页看的是已经生成好的幻灯片与讲稿（字幕条放的就是这一页的讲稿）。
          AI 教师语音授课在 P2 阶段接入，AI 同学讨论与举手发言在 P3 阶段接入。
        </template>
      </t-alert>
    </div>

    <div class="cls-body">
      <ClassroomStage
        :page="currentPage"
        :course-title="course?.title ?? ''"
        :page-count="pageCount"
        :can-prev="canPrev"
        :can-next="canNext"
        :loading="loading"
        :empty-title="emptyTitle"
        :empty-text="emptyText"
        @prev="go(-1)"
        @next="go(1)"
      />
      <ClassroomPanel :outline="outline" :current-no="pageNo" @jump="jump" />
    </div>
  </div>
</template>

<style scoped>
.cls {
  height: calc(100vh - 60px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* 顶栏（原型 .cls-header） */
.cls-header {
  display: flex;
  align-items: center;
  gap: 16px;
  height: 56px;
  padding: 0 20px;
  background: var(--td-bg-container);
  border-bottom: 1px solid var(--td-component-stroke);
  flex-shrink: 0;
}

.cls-header .back {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--td-radius-default);
  cursor: pointer;
  color: var(--td-text-secondary);
}

.cls-header .back:hover {
  background: var(--td-bg-container-hover);
  color: var(--td-text-primary);
}

/* 课程标题可能很长：让它先省略，别把右边的按钮挤出屏幕 */
.cls-header__info {
  min-width: 0;
}

.cls-header__title {
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cls-header__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 3px;
}

.cls-header .spacer {
  flex: 1;
}

.cls-banner {
  padding: 12px 20px 0;
}

.cls-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
</style>
