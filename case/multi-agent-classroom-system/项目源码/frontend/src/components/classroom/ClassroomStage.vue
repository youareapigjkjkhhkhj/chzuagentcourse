<script setup lang="ts">
/**
 * 课堂左侧舞台：幻灯片 + 教具 + 字幕 + 测验 + 播放控制。
 *
 * 版式取自 `产品原型/classroom.html`。**P3 起这一块完全由会话驱动** ——
 * 页号、进度、状态都不是这里算的，是 store 从服务端的 `state` 事件收下来的。
 * 所以这一层只做两件事：把状态画出来，把意图发上去（`play` / `pause` /
 * `seek` / `speed`）。**一个本地推算的页号都没有**，理由见 `stores/classroom.ts`
 * 开头那条纪律。
 *
 * 教具条（激光笔/聚光灯/画笔/橡皮）在这一层**本地生效**：光点、光圈、笔迹
 * 都画在幻灯片上面那层覆盖层里，不进幻灯片本体、不进 store、也不发 WS。
 * 跨端同步（老师画给学生看）是 P6.6 的事（P3 §2.4 / §10.2 的口径）——
 * 所以刷新一下标注就没了，这是说好的，不是丢了。
 *
 * 白板 Tab 的画笔是另一回事：那条走服务端（见 `ClassroomBoard.vue`）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import PageSlide from '@/components/workbench/PageSlide.vue'
import { captionParts, formatClock } from '@/utils/voice'
import type { AudioBeat, CoursePageItem } from '@/types/api'
import type { ClassroomStatus, SpeakPayload } from '@/types/classroom'

const props = withDefaults(
  defineProps<{
    page?: CoursePageItem | null
    courseTitle?: string
    pageCount?: number
    canPrev?: boolean
    canNext?: boolean
    loading?: boolean
    emptyTitle?: string
    emptyText?: string

    // --- 会话状态（全部来自 store，不在这里推算）---
    status?: ClassroomStatus
    /** 当前这一条发言（`speak`）。**空音频是常态**，见 `SpeakPayload.audioUrl`。 */
    speaking?: SpeakPayload | null
    /** 最后一条字幕的文字（没有发言时显示它） */
    subtitle?: string
    /** 谁在说。用于字幕左边的署名。 */
    speakerName?: string
    /** 音频真的在响（没有音频的发言永远是 false，但不代表它没说） */
    playing?: boolean
    /** 这一段播到第几毫秒（字级高亮用） */
    positionMs?: number
    /** 当前 beat 的字级时间戳（来自音频清单）。没有就退成整句显示。 */
    cues?: AudioBeat | null

    pageNo?: number
    elapsedMs?: number
    totalMs?: number
    speed?: number
    /** 这节课有没有声音（没有时播放键置灰并说明原因，P2-G3 的口径） */
    hasAudio?: boolean
    silentReason?: string
  }>(),
  {
    page: null,
    courseTitle: '',
    pageCount: 0,
    canPrev: false,
    canNext: false,
    loading: false,
    emptyTitle: '还没有可讲授的课程',
    emptyText: '',
    status: 'idle',
    speaking: null,
    subtitle: '',
    speakerName: '',
    playing: false,
    positionMs: 0,
    cues: null,
    pageNo: 0,
    elapsedMs: 0,
    totalMs: 0,
    speed: 1,
    hasAudio: false,
    silentReason: '',
  },
)

const emit = defineEmits<{
  prev: []
  next: []
  play: []
  pause: []
  /** 跳到第几页（进度条与「跳到这一页」都走它） */
  seek: [pageNo: number]
  speed: [value: number]
}>()

const TOOLS = [
  { key: 'laser', title: '激光笔', hint: '一个红点跟着鼠标走' },
  { key: 'spotlight', title: '聚光灯', hint: '压暗四周，只照亮鼠标附近；滚轮调光圈大小' },
  { key: 'pen', title: '画笔', hint: '按住左键在幻灯片上画' },
  { key: 'eraser', title: '橡皮擦', hint: '点（或拖）到笔迹上擦掉那一笔' },
] as const

type ToolKey = (typeof TOOLS)[number]['key']

/** 空串 = 不用教具。 */
const activeTool = ref<ToolKey | ''>('')

/** 再点一次同一个工具就收起 —— 讲下一页时不该还挂着上一页那个光圈。 */
function pickTool(key: ToolKey) {
  activeTool.value = activeTool.value === key ? '' : key
}

/* --- 幻灯片的大小：这一格能给多少，就把它放到多大 --- */

/** 幻灯片的设计尺寸。里面所有 px（字号、间距、图）都是照它定的。 */
const SLIDE_W = 960

const stageEl = ref<HTMLElement | null>(null)
const stageZoom = ref(1)
let zoomObserver: ResizeObserver | null = null

/**
 * 量一下舞台这一格有多宽，幻灯片就整体缩放多少（1 = 原尺寸）。
 *
 * **为什么不干脆让盒子变大**：幻灯片里的字号与间距是照 960 宽定的 px，
 * 盒子一宽，字还是 14px、空白却多出一大块 —— 区域大了，内容没大。
 * 缩放走的是 `zoom`：它**连同布局尺寸一起缩**，所以父元素量到的就是缩放后的框，
 * 上面那层教具（笔迹按百分比定位）照样对得齐；`transform: scale` 做不到这一点
 * （它不改变占位，父元素量到的还是原尺寸）。
 *
 * jsdom 里没有 ResizeObserver：测试拿默认的 1 跑就行，不必为它造个假的。
 */
onMounted(() => {
  if (typeof ResizeObserver === 'undefined') return
  zoomObserver = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width ?? 0
    if (!width) return
    // 留三位小数：再多只是让每一次观测都算成「变了」，白白重排
    const next = Math.round((width / SLIDE_W) * 1000) / 1000
    if (next !== stageZoom.value) stageZoom.value = next
  })
  if (stageEl.value) zoomObserver.observe(stageEl.value)
})

onBeforeUnmount(() => {
  zoomObserver?.disconnect()
  zoomObserver = null
})

/* --- 课堂标注（纯本地，P3 §2.4） --- */

/** 归一化画布：16:9，宽 1000、高 562.5。坐标与舞台像素尺寸脱钩，窗口缩放笔迹不跑位。 */
const INK_W = 1000
const INK_H = 562.5

/** 这份 SVG 的 mask / 渐变要个 id：同一个页面里出现两个舞台时不能撞。 */
const inkUid = Math.random().toString(36).slice(2, 8)
const spotMaskId = `stage-spot-mask-${inkUid}`
const spotFadeId = `stage-spot-fade-${inkUid}`

interface Stroke {
  id: number
  /** 扁平点列 `[x0,y0,x1,y1,…]`（`polyline` 就是这个顺序） */
  points: number[]
}

/**
 * 笔迹**按页存**：第 3 页圈的重点不该跟到第 4 页去。
 * P6.6 要跨端同步时，这份「页码 → 笔迹」正是要发上去的形状。
 */
const inkByPage = ref<Record<number, Stroke[]>>({})
const strokes = computed<Stroke[]>(() => inkByPage.value[props.pageNo] ?? [])

const screenEl = ref<HTMLElement | null>(null)
/** 鼠标在归一化坐标里的位置：激光笔与聚光灯跟着它走。 */
const cursor = ref({ x: INK_W / 2, y: INK_H / 2 })
/** 鼠标还在幻灯片上吗（移出去就把光点/光圈收掉）。 */
const cursorIn = ref(false)
/** 正按着左键（画笔在续笔，橡皮在擦）。 */
let holding = false
let strokeId = 0

/** 屏幕坐标 → 归一化坐标。拿不到舞台尺寸就返回 null（还没量出来/已经卸载）。 */
function toInk(event: PointerEvent): { x: number; y: number } | null {
  const box = screenEl.value?.getBoundingClientRect()
  if (!box || !box.width || !box.height) return null
  return {
    x: ((event.clientX - box.left) / box.width) * INK_W,
    y: ((event.clientY - box.top) / box.height) * INK_H,
  }
}

function addStroke(at: { x: number; y: number }) {
  const page = props.pageNo
  inkByPage.value[page] = [
    ...(inkByPage.value[page] ?? []),
    { id: (strokeId += 1), points: [at.x, at.y] },
  ]
}

function extendStroke(at: { x: number; y: number }) {
  const list = inkByPage.value[props.pageNo]
  const last = list?.[list.length - 1]
  if (last) last.points.push(at.x, at.y)
}

/** 橡皮的判定半径：屏幕上 8px 折算成归一化单位。 */
const ERASER_PX = 8

function eraseAt(at: { x: number; y: number }) {
  const box = screenEl.value?.getBoundingClientRect()
  const limit = box && box.width ? (ERASER_PX / box.width) * INK_W : ERASER_PX
  const list = inkByPage.value[props.pageNo]
  if (!list?.length) return
  // 从后往前找：后画的压在上面，先擦到的该是它
  for (let i = list.length - 1; i >= 0; i -= 1) {
    if (nearStroke(list[i].points, at.x, at.y, limit)) {
      inkByPage.value[props.pageNo] = list.filter((row) => row !== list[i])
      return
    }
  }
}

/** 这个点离某一笔够近吗。 */
function nearStroke(points: number[], x: number, y: number, limit: number): boolean {
  if (points.length < 4) {
    return points.length === 2 && Math.hypot(points[0] - x, points[1] - y) <= limit
  }
  for (let i = 0; i + 3 < points.length; i += 2) {
    if (distanceToSegment(x, y, points[i], points[i + 1], points[i + 2], points[i + 3]) <= limit) {
      return true
    }
  }
  return false
}

/** 点到线段的最短距离：一笔只采样到几个点时，只看顶点会漏掉长线段的中段。 */
function distanceToSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const len = dx * dx + dy * dy
  const t = len ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / len)) : 0
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

function onDown(event: PointerEvent) {
  if (!activeTool.value) return
  const at = toInk(event)
  if (!at) return
  // 画的时候别顺手选中幻灯片上的文字
  event.preventDefault()
  cursor.value = at
  cursorIn.value = true
  if (activeTool.value === 'pen') addStroke(at)
  else if (activeTool.value === 'eraser') eraseAt(at)
  else return
  holding = true
  // 抓指针：拖到幻灯片外面松手也算收笔，笔迹不会一直连到边框上
  const target = event.currentTarget as HTMLElement | null
  target?.setPointerCapture?.(event.pointerId)
}

function onMove(event: PointerEvent) {
  const at = toInk(event)
  if (!at) return
  cursor.value = at
  cursorIn.value = true
  if (!holding) return
  if (activeTool.value === 'pen') extendStroke(at)
  else if (activeTool.value === 'eraser') eraseAt(at)
}

function onUp() {
  holding = false
}

/**
 * 聚光灯的光圈大小跟着滚轮走。
 *
 * 单位是归一化坐标（画布 1000 宽 ≈ 舞台上那 960px），80~340 大致就是屏幕上
 * 一个直径 15%~65% 舞台宽的圆。
 */
const SPOT_MIN = 80
const SPOT_MAX = 340
const spotRadius = ref(180)

function onWheel(event: WheelEvent) {
  if (activeTool.value !== 'spotlight') return
  // 只有真在调光圈时才拦滚动，不然这一层会把整页的滚动吃掉
  event.preventDefault()
  const step = event.deltaY < 0 ? -20 : 20
  spotRadius.value = Math.min(SPOT_MAX, Math.max(SPOT_MIN, spotRadius.value + step))
}

/** 清除标注：只清这一页（笔迹本来就是一页一份）。 */
function clearInk() {
  if (!strokes.value.length) return
  inkByPage.value[props.pageNo] = []
}

/** `polyline` 的 `points` 要字符串，数组直接绑会依赖 Vue 的隐式 toString。 */
const pointsOf = (stroke: Stroke) => stroke.points.join(' ')

/**
 * 字幕显示的那一句。
 *
 * 优先**正在说的这一条**（`speak` 的全文）；没有发言时退到 store 里最后一条
 * 字幕。两者都没有就是一句占位 —— 课堂还没开讲。
 */
const caption = computed(() => {
  if (props.speaking?.text) return props.speaking.text
  if (props.subtitle) return props.subtitle
  if (props.loading) return '正在读取这门课…'
  return '这节课还没开始。'
})

const who = computed(() => props.speaking?.speaker?.name || props.speakerName || '')

/**
 * 逐词高亮的三段。
 *
 * 时间戳来自**音频清单**里那个 beat（与 P2 的播放器同一份），按 `beatId` 对起来。
 * 拿不到（这一句没有音频、清单里没有这一句、片段拼不回整句）就是 null，
 * 退成整句显示 —— 少一个动画，好过多一块和声音对不上的假高亮（见 `captionParts`）。
 */
const parts = computed(() => {
  if (!props.cues) return null
  const beatId = props.speaking?.beats?.[0]
  if (!beatId || props.cues.beatId !== beatId) return null
  return captionParts(props.cues, props.positionMs)
})

/**
 * 幻灯片上的图该揭示到第几拍（`PageSlide` 的 `beat`）。
 *
 * 讲稿的每一拍都是一次发言（`runtime` 那边一个 beat 一条 turn），而这一句
 * 讲的是哪一拍，服务端写在 `speaking.beats` 里 —— 这里按 beatId 在这一页的
 * 讲稿里查位置，不自己解析 `p3-b1` 这种串（编法是服务端的事，前端解析等于
 * 把那个约定抄了第二份）。
 *
 * **只进不退**：一句讲完 `speaking` 就清空了，跟着它回退的话，老师一停下来
 * 图就缩回去一半 —— 那一页讲到哪儿，图就长到哪儿。翻页时归零重新长。
 *
 * 取不到（这一页没讲稿、这句是答疑不是讲稿）就是 `null`，图整张全显示。
 */
const revealedBeat = ref<number | null>(null)

watch(
  () => [props.page?.pageNo, props.speaking?.pageNo, props.speaking?.beats?.[0]] as const,
  ([pageNo, spokenPage, beatId], prev) => {
    // 第一次进来（`immediate`）没有旧值，也当翻页处理 —— 本来就是从头开始
    if (prev?.[0] !== pageNo) revealedBeat.value = null
    // 讲的是别的页（翻页有半拍延迟）时不动这一页的图
    if (!beatId || spokenPage !== pageNo) return
    const at = (props.page?.dsl?.narration ?? []).findIndex((beat) => beat.beatId === beatId)
    if (at < 0) return
    if (revealedBeat.value === null || at > revealedBeat.value) revealedBeat.value = at
  },
  { immediate: true },
)

/** 进度条按整课算：F3-2 要的是「07:32 / 25:00 真实计算」。 */
const percent = computed(() => {
  if (props.totalMs <= 0) return 0
  return Math.min(100, Math.max(0, (props.elapsedMs / props.totalMs) * 100))
})

const clock = computed(() => ({
  at: formatClock(props.elapsedMs),
  total: formatClock(props.totalMs),
}))

/**
 * 播放键在什么状态下该显示什么。
 *
 * 只有 `lecture` 与 `discussing` 里的「暂停」是有意义的；`quiz_wait` 时老师在
 * 等学生答题，按暂停会把这堂课卡在半个测验上（后端会 40901 挡回来，但那个
 * 红条不该出现），所以那两拍把按钮置灰并说清原因。
 */
const busy = computed(() => props.status === 'quiz_wait' || props.status === 'board_show')
const playTitle = computed(() => {
  if (busy.value) return '等这一步走完再继续'
  // 开讲这件事在右上角（这一页的按钮只管播放中/暂停），所以这里说的是去哪按
  if (props.status === 'idle') return '在右上角点「开始上课」'
  if (props.status === 'ended') return '这节课已经下课了'
  return props.playing || props.status === 'lecture' ? '暂停' : '继续'
})
const canToggle = computed(
  () => props.status !== 'ended' && props.status !== 'idle' && !busy.value,
)

/**
 * 倍速。**发上去的是倍速本身**（`speed{value}`），不是「切下一档」——
 * 服务端是唯一知道当前速度的地方，把「下一档」放在前端算，两个标签页
 * 同时点就会各按各的认知往前跳（P3-A13）。
 */
const RATE_STEPS = [1.0, 1.25, 1.5, 2.0]

function cycleRate() {
  const at = RATE_STEPS.indexOf(props.speed)
  emit('speed', RATE_STEPS[(at + 1) % RATE_STEPS.length])
}

/**
 * 拖进度条 = 跳到那一页（F2-5 的口径）。
 *
 * 整课的毫秒数摊到各页上算出目标页号 —— 课堂的位置本来就是「页 + beat」，
 * 没有「页中间的某一秒」这种东西可以跳。
 */
function seekBy(event: unknown) {
  const value = Number((event as { percent?: number })?.percent ?? 0)
  const ratio = Math.min(1, Math.max(0, value / 100))
  if (props.totalMs <= 0 || !props.pageCount) return
  const target = Math.min(
    props.pageCount,
    Math.max(1, Math.floor((ratio * props.totalMs) / (props.totalMs / props.pageCount)) + 1),
  )
  if (target !== props.pageNo) emit('seek', target)
}

/**
 * 播放键：**按下之后发生什么，要与图标说的是同一件事**。
 *
 * 图标画的是暂停 ⟺ 课正在走（`lecture` / `discussing`），所以那两种状态
 * 点下去就是「停住」；其余（暂停中）是「继续」。**不看 `playing`**：
 * 有没有声音与课走不走是两件事 —— 一节没合成语音的课也照样在讲。
 */
function togglePlay() {
  if (!canToggle.value) return
  if (props.status === 'lecture' || props.status === 'discussing') emit('pause')
  else emit('play')
}
</script>

<template>
  <div class="stage-wrap">
    <div ref="stageEl" class="stage">
      <!-- 舞台 = 幻灯片 + 一层盖在上面的教具层。覆盖层的尺寸跟着幻灯片走，
           所以量覆盖层的框就等于量幻灯片（笔迹坐标都从这儿来）。 -->
      <div
        v-if="page"
        ref="screenEl"
        class="stage-screen"
        :style="{ '--stage-zoom': stageZoom }"
      >
        <PageSlide
          variant="classroom"
          :page="page"
          :course-title="courseTitle"
          :page-count="pageCount"
          :beat="revealedBeat"
        />

        <div
          class="stage-ink"
          :class="activeTool ? `is-${activeTool}` : ''"
          @pointerdown="onDown"
          @pointermove="onMove"
          @pointerup="onUp"
          @pointercancel="onUp"
          @pointerleave="cursorIn = false"
          @wheel="onWheel"
        >
          <!-- viewBox 与舞台同为 16:9，所以 `none` 不会把圆拉成椭圆；
               笔迹用非缩放描边，窗口大小变了线还是那么粗。 -->
          <svg class="ink-svg" :viewBox="`0 0 ${INK_W} ${INK_H}`" preserveAspectRatio="none">
            <defs>
              <radialGradient :id="spotFadeId">
                <stop offset="72%" stop-color="#000" />
                <stop offset="100%" stop-color="#fff" />
              </radialGradient>
              <mask
                :id="spotMaskId"
                maskUnits="userSpaceOnUse"
                x="0"
                y="0"
                :width="INK_W"
                :height="INK_H"
              >
                <rect x="0" y="0" :width="INK_W" :height="INK_H" fill="#fff" />
                <circle
                  :cx="cursor.x"
                  :cy="cursor.y"
                  :r="spotRadius"
                  :fill="`url(#${spotFadeId})`"
                />
              </mask>
            </defs>

            <!-- 聚光灯：整片压暗，中间那个圆被 mask 挖空（边缘渐变，不是硬边） -->
            <rect
              v-if="activeTool === 'spotlight' && cursorIn"
              x="0"
              y="0"
              :width="INK_W"
              :height="INK_H"
              fill="rgba(2, 6, 23, 0.74)"
              :mask="`url(#${spotMaskId})`"
            />

            <polyline
              v-for="stroke in strokes"
              :key="stroke.id"
              :points="pointsOf(stroke)"
              fill="none"
              stroke="#e34d59"
              stroke-width="3.5"
              stroke-linecap="round"
              stroke-linejoin="round"
              vector-effect="non-scaling-stroke"
            />
          </svg>

          <span
            v-if="activeTool === 'laser' && cursorIn"
            class="ink-laser"
            :style="{
              left: `${(cursor.x / INK_W) * 100}%`,
              top: `${(cursor.y / INK_H) * 100}%`,
            }"
          />
        </div>
      </div>
      <div v-else class="slide">
        <t-empty :title="emptyTitle" :description="emptyText" />
      </div>

    </div>

    <!-- 字幕条：正在说的那一句，逐词高亮（拿得到时间戳时才高亮） -->
    <div class="subtitle" :class="{ 'is-live': Boolean(speaking) }">
      <span class="who">{{ who || 'AI 教师' }}</span>
      <span class="text">
        <template v-if="parts">
          <span>{{ parts.before }}</span><span class="now">{{ parts.active }}</span
          ><span>{{ parts.after }}</span>
        </template>
        <template v-else>{{ caption }}</template>
      </span>
    </div>

    <!--
      教具（激光笔 / 聚光灯 / 画笔 / 橡皮 / 清除标注）。

      **放在幻灯片外面**：原来是浮在幻灯片右缘、上下居中的一条竖栏，正压着正文
      —— 图左文右的版式里被切掉的是右边那栏的字。挪到字幕与播放条之间、右对齐到
      幻灯片那一条轴上，任何窗口宽度下都不再盖住内容。
      也不塞进播放条里：窄屏（或测验弹框开着一让位）幻灯片只剩六百来像素宽，
      播放条本身就快排满了，再挤五个按钮就要溢出。
    -->
    <div class="stage-tools">
      <span
        v-for="tool in TOOLS"
        :key="tool.key"
        class="tool"
        :class="{ 'is-active': activeTool === tool.key }"
        :title="`${tool.title} —— ${tool.hint}`"
        @click="pickTool(tool.key)"
      >
        <svg
          v-if="tool.key === 'laser'"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
        >
          <circle cx="12" cy="12" r="3" />
          <circle cx="12" cy="12" r="7" stroke-dasharray="3 3" />
        </svg>
        <svg
          v-else-if="tool.key === 'spotlight'"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
        >
          <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.8.7 1 1.5 1 2.5h6c0-1 .2-1.8 1-2.5A6 6 0 0 0 12 3Z" />
        </svg>
        <svg
          v-else-if="tool.key === 'pen'"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
        >
          <path d="m14 6 4 4L8.5 19.5a2.1 2.1 0 0 1-3-3L14 6ZM13 7l4 4M16 4l4 4" />
        </svg>
        <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="m9 15 8.5-8.5a2.1 2.1 0 0 1 3 3L12 18H8l-3 3h13" />
        </svg>
      </span>
      <span
        class="tool"
        :class="{ 'is-dim': !strokes.length }"
        :title="strokes.length ? '清除标注 —— 擦掉这一页画过的所有笔迹' : '这一页还没有标注'"
        @click="clearInk"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <path
            d="M4 7h16M10 11v6M14 11v6M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M9 7V4h6v3"
          />
        </svg>
      </span>
    </div>

    <!-- 播放控制 -->
    <div class="player-bar">
      <button
        class="play-btn"
        :disabled="!canToggle"
        :title="playTitle"
        @click="togglePlay"
      >
        <svg v-if="playing || status === 'lecture'" viewBox="0 0 24 24" fill="currentColor">
          <path d="M7 5h4v14H7zM13 5h4v14h-4z" />
        </svg>
        <svg v-else viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l11-6.5-11-6.5Z" /></svg>
      </button>
      <t-button variant="outline" :disabled="!canPrev" @click="emit('prev')">
        <template #icon>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M15 5l-7 7 7 7" />
          </svg>
        </template>
        上一页
      </t-button>
      <span class="page-indicator">
        第 <b>{{ pageNo || '—' }}</b> / {{ pageCount || '—' }} 页
      </span>
      <!-- 没有声音时说出来：一节没合成语音的课照上，但学生该知道为什么没声音 -->
      <t-tag v-if="!hasAudio && silentReason" variant="light" :title="silentReason">纯文字</t-tag>
      <t-button variant="outline" :disabled="!canNext" @click="emit('next')">
        下一页
        <template #suffix>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M9 5l7 7-7 7" />
          </svg>
        </template>
      </t-button>
      <div class="player-progress">
        <span class="mono">{{ clock.at }}</span>
        <t-progress
          :percentage="percent"
          :label="false"
          :disabled="!canToggle"
          @change="seekBy"
        />
        <span class="mono">{{ clock.total }}</span>
      </div>
      <t-button variant="text" :title="'播放倍速（当前 ' + speed + 'x）'" @click="cycleRate">
        {{ speed.toFixed(2).replace(/0$/, '') }}x
      </t-button>
    </div>
  </div>
</template>
<style scoped src="../../styles/components/classroom/ClassroomStage.css"></style>
