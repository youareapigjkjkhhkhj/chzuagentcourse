<script setup lang="ts">
/**
 * 板书面板（F3-9 / P3-A8）：把 `board_strokes` 画出来，按笔画顺序逐笔绘制。
 *
 * **笔画是归一化坐标**（0~1，见后端 `board.py`），画的时候乘画布尺寸。
 * 这一点必须守住：归一化的意义是同一份板书在任何尺寸的屏幕上都画得对，
 * 而把像素坐标存进库里的那一刻，这块板书就只在那一种屏幕上对了。
 *
 * **逐笔绘制而不是一次全画出来**：`durMs` 记的是「老师在写这一笔上花了多久」，
 * 照着它铺开，白板上出现的顺序与节奏就跟当时课堂上一样 —— 那是回放要还原的
 * 东西。一次全画出来也对（图是同一张），但看的人就不知道老师先写的哪一笔。
 *
 * 动画用 `requestAnimationFrame` 自己算进度，不用 CSS 的 `stroke-dashoffset`：
 * 后者要先把每个点集转成 `<path>` 才算得出路径长度，而 `polyline` 的
 * `getTotalLength()` 在 jsdom 里是 0（测试里量不到）。自己按点数铺开，
 * 在任何环境里算出来的都是同一个值。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import type { BoardStroke, StrokePoint } from '@/types/classroom'

/** 逻辑画布尺寸。比例是 16:9，与幻灯片一致 —— 板书才贴在幻灯片上。 */
const VIEW_W = 1000
const VIEW_H = 562

const props = withDefaults(
  defineProps<{
    strokes?: BoardStroke[]
    /** 外面按下「回看本页板书」时 +1，用来重放。 */
    replayKey?: number
    /** 正在跟着课走（讲台上那一页）。不在讲台上时提示「这是过去的第 N 页」。 */
    live?: boolean
    loading?: boolean
    /**
     * 一上来就整页画完，不逐笔重放（记录页的快照用）。
     *
     * 回放是对着**正在上的课**才成立的事 —— 那时「先写哪一笔」就是刚刚发生
     * 的东西。回看一堂 25 分钟前的课，人要的是那页板书长什么样：进来先等
     * 几秒钟让几页板书各画一遍，读到的是「还没画完」，不是「写的是什么」。
     * 「重放」按钮在任何一种下都还是逐笔的。
     */
    instant?: boolean
  }>(),
  { strokes: () => [], replayKey: 0, live: true, loading: false, instant: false },
)

const elapsedMs = ref(0)
let frame = 0
let startedAt = 0

/** 每一笔什么时候开始画、画多久。时长缺失（0）时给一个短默认值。 */
const schedule = computed(() => {
  let cursor = 0
  return props.strokes.map((stroke) => {
    const dur = stroke.durMs > 0 ? stroke.durMs : 400
    const item = { stroke, start: cursor, dur }
    cursor += dur
    return item
  })
})

const totalMs = computed(() => {
  const list = schedule.value
  const last = list[list.length - 1]
  return last ? last.start + last.dur : 0
})

/** 已经画到第几笔了（按时间算，不是按 index 逐个补间）。 */
const drawn = computed(() =>
  schedule.value.map((item) => ({
    stroke: item.stroke,
    // 0~1：这一笔画了多少。1 = 整笔画完
    progress: props.strokes.length ? clamp01((elapsedMs.value - item.start) / item.dur) : 0,
    // 文字笔画的排版（换行 / 折行 / 夹回画布）。在这里算一次，
    // 模板里就不必为一个 `<text>` 反复调六遍同一个函数。
    text: item.stroke.tool === 'text' ? textBlock(item.stroke) : null,
  })),
)

const done = computed(() => props.strokes.length > 0 && elapsedMs.value >= totalMs.value)

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

/** 重放：从 0 开始按 `durMs` 铺开。播完就停（不留着 rAF 转圈）。 */
function replay(): void {
  cancel()
  elapsedMs.value = 0
  if (!props.strokes.length) return
  startedAt = performance.now()
  const step = () => {
    elapsedMs.value = performance.now() - startedAt
    if (elapsedMs.value >= totalMs.value) {
      frame = 0
      return
    }
    frame = requestAnimationFrame(step)
  }
  frame = requestAnimationFrame(step)
}

function cancel(): void {
  if (frame) cancelAnimationFrame(frame)
  frame = 0
}

/** 直接铺到画完：一帧都不走，笔画一次全在。 */
function drawAll(): void {
  cancel()
  elapsedMs.value = totalMs.value
}

// 换页（或来了新笔画）就重画一遍：留着上一页的进度会让新板书只画一半。
// 记录页（`instant`）铺到画完，讲台上（默认）按 `durMs` 逐笔重放。
watch(
  () => props.strokes,
  () => (props.instant ? drawAll() : replay()),
  { immediate: true, deep: false },
)

// 「重放」按钮：两种页面下都是逐笔的 —— 按下去要的就是那个过程
watch(() => props.replayKey, () => replay())

onBeforeUnmount(cancel)

// --- 画每一笔 ---

function px(point: StrokePoint): [number, number] {
  return [point.x * VIEW_W, point.y * VIEW_H]
}

function toPairs(points: StrokePoint[]): string {
  return points.map((point) => px(point).join(',')).join(' ')
}

/**
 * 这一笔**此刻**该露出多少个点。
 *
 * 至少 2 个（一个点画不出线），画完给全部。中间按比例取整 —— 折线是「一笔」
 * 不是「一帧一帧的动画」，取整只影响 60fps 下的平滑度，不影响形状。
 */
function visiblePoints(points: StrokePoint[], progress: number): StrokePoint[] {
  if (progress >= 1) return points
  const count = Math.max(2, Math.ceil(points.length * progress))
  return points.slice(0, Math.min(points.length, count))
}

/** 箭头的三角头：按最后一小段的方向摆。 */
function arrowHead(points: StrokePoint[]): string {
  if (points.length < 2) return ''
  const [x1, y1] = px(points[points.length - 2])
  const [x2, y2] = px(points[points.length - 1])
  const angle = Math.atan2(y2 - y1, x2 - x1)
  const size = 14
  const left = `${x2 - size * Math.cos(angle - 0.4)},${y2 - size * Math.sin(angle - 0.4)}`
  const right = `${x2 - size * Math.cos(angle + 0.4)},${y2 - size * Math.sin(angle + 0.4)}`
  return `${left} ${x2},${y2} ${right}`
}

/** 矩形 / 椭圆取点集的包围盒。点少于两个就画个小方块，别画出一条看不见的线。 */
function boxOf(points: StrokePoint[]) {
  const xs = points.map((point) => point.x)
  const ys = points.map((point) => point.y)
  const x = Math.min(...xs) * VIEW_W
  const y = Math.min(...ys) * VIEW_H
  const w = Math.max(8, (Math.max(...xs) - Math.min(...xs)) * VIEW_W)
  const h = Math.max(8, (Math.max(...ys) - Math.min(...ys)) * VIEW_H)
  return { x, y, w, h }
}

/** 文字的位置。`clean()` 会给没写坐标的 text 补一个 `[0.12, 0.18]`。 */
function textAt(points: StrokePoint[]): [number, number] {
  const [x, y] = points.length ? px(points[0]) : [VIEW_W * 0.12, VIEW_H * 0.18]
  return [x, y]
}

const strokeWidth = (stroke: BoardStroke) => Math.max(1, stroke.width || 3)

// --- 文字笔画（F3-9）---

/** 画布边缘留白。文字贴边看着像被裁掉了。 */
const TEXT_MARGIN = 14

/** 行高（相对字号）。多行文字的第一行与第二行之间就是这个距离。 */
const LINE_RATIO = 1.45

/**
 * 一个字占多宽（相对字号）：中日韩是全角，其余按半角估。
 *
 * 估宽只用来排版，不求精确 —— 估宽了多折一行（难看但读得到），
 * 估窄了才会溢出画布（那才是读不到）。
 */
function charUnits(char: string): number {
  return char.charCodeAt(0) < 0x2e80 ? 0.55 : 1
}

function measure(line: string, size: number): number {
  let units = 0
  for (const char of line) units += charUnits(char)
  return units * size
}

/** 一行太宽就折成几行。折点按估宽走 —— 中英混排靠字数折不准（宽度差一倍）。 */
function wrapLine(line: string, size: number, maxWidth: number): string[] {
  if (measure(line, size) <= maxWidth) return [line]
  const out: string[] = []
  let current = ''
  for (const char of line) {
    if (current && measure(current + char, size) > maxWidth) {
      out.push(current)
      current = char
    } else {
      current += char
    }
  }
  out.push(current)
  return out
}

/**
 * 一笔文字怎么排：**换行 | 折行 | 夹回画布**。
 *
 * 三件事必须一起做，少一件都会让人「在白板上只看到几个字」：
 *
 * - 模型给的文字是**多行**的（`目录\n1. 专家混合概览\n2. 稀疏路由`），
 *   而 SVG 的 `<text>` 不认 `\n` —— 不拆开就整段挤在一行里。
 * - 挤在一行之后，起点靠右的那几笔（比如 `[[0.78, 0.68]]`）只有开头
 *   几个字落在画布内，剩下的全在画布外被裁掉。
 * - 单行过长（上限 80 字）时折行，否则夹了起点也还是会从右边溢出去。
 */
function textBlock(stroke: BoardStroke): { x: number; y: number; size: number; lines: string[] } {
  const size = Math.max(14, strokeWidth(stroke) * 6)
  const maxWidth = VIEW_W - TEXT_MARGIN * 2
  const lines = (stroke.text || '')
    .split('\n')
    .flatMap((line) => wrapLine(line, size, maxWidth))
  while (lines.length > 1 && !lines[lines.length - 1].trim()) lines.pop()
  if (!lines.length) lines.push('')

  const lineHeight = size * LINE_RATIO
  const [rawX, rawY] = textAt(stroke.points)
  const width = Math.max(...lines.map((line) => measure(line, size)))

  // 夹的是**整块**的位置：把起点拉回来，让最宽的一行也在画布内。
  // 右边界用 max 兜一下：整块比画布还宽时，至少起点还在左留白上。
  const x = Math.min(Math.max(TEXT_MARGIN, rawX), Math.max(TEXT_MARGIN, VIEW_W - TEXT_MARGIN - width))
  // 纵向同理：第一行的基线在 y，最后一行在 y + (n-1) 个行高处
  const top = TEXT_MARGIN + size
  const bottom = VIEW_H - TEXT_MARGIN - (lines.length - 1) * lineHeight
  const y = Math.min(Math.max(top, rawY), Math.max(top, bottom))

  return { x, y, size, lines }
}
</script>

<template>
  <div class="board">
    <div class="board__canvas">
      <svg :viewBox="`0 0 ${VIEW_W} ${VIEW_H}`" role="img" aria-label="课堂板书">
        <g v-for="item in drawn" :key="item.stroke.id">
          <template v-if="item.progress > 0">
            <polyline
              v-if="item.stroke.tool === 'polyline' || item.stroke.tool === 'curve'"
              :points="toPairs(visiblePoints(item.stroke.points, item.progress))"
              fill="none"
              :stroke="item.stroke.color || 'var(--td-brand-color)'"
              :stroke-width="strokeWidth(item.stroke)"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <g v-else-if="item.stroke.tool === 'arrow'">
              <polyline
                :points="toPairs(visiblePoints(item.stroke.points, item.progress))"
                fill="none"
                :stroke="item.stroke.color || 'var(--td-brand-color)'"
                :stroke-width="strokeWidth(item.stroke)"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
              <polygon
                v-if="item.progress >= 1"
                :points="arrowHead(item.stroke.points)"
                :fill="item.stroke.color || 'var(--td-brand-color)'"
              />
            </g>
            <rect
              v-else-if="item.stroke.tool === 'rect'"
              v-bind="boxOf(item.stroke.points)"
              fill="none"
              :stroke="item.stroke.color || 'var(--td-brand-color)'"
              :stroke-width="strokeWidth(item.stroke)"
              :opacity="item.progress"
            />
            <ellipse
              v-else-if="item.stroke.tool === 'ellipse'"
              :cx="boxOf(item.stroke.points).x + boxOf(item.stroke.points).w / 2"
              :cy="boxOf(item.stroke.points).y + boxOf(item.stroke.points).h / 2"
              :rx="boxOf(item.stroke.points).w / 2"
              :ry="boxOf(item.stroke.points).h / 2"
              fill="none"
              :stroke="item.stroke.color || 'var(--td-brand-color)'"
              :stroke-width="strokeWidth(item.stroke)"
              :opacity="item.progress"
            />
            <!-- 文字：一行一个 `<tspan>`。`<text>` 自己会把裸的 `\n` 当空格，
                 所以多行的文字必须拆成 tspan —— 见 `textBlock` -->
            <text
              v-else-if="item.text"
              :x="item.text.x"
              :y="item.text.y"
              :fill="item.stroke.color || 'var(--td-text-primary)'"
              :font-size="item.text.size"
              :opacity="item.progress"
            >
              <tspan
                v-for="(line, index) in item.text.lines"
                :key="index"
                :x="item.text.x"
                :dy="index === 0 ? 0 : item.text.size * LINE_RATIO"
              >{{ line }}</tspan>
            </text>
          </template>
        </g>
      </svg>

      <div v-if="!strokes.length" class="board__empty">
        <t-empty
          size="small"
          :description="
            loading
              ? '正在读取这一页的板书…'
              : live
                ? 'AI 教师讲到有板书的页面时，笔画会在这里一笔一笔画出来。'
                : '这一页没有板书。'
          "
        />
      </div>
    </div>

    <div class="board__bar">
      <span class="board__count">
        {{ drawn.filter((item) => item.progress >= 1).length }} / {{ strokes.length }} 笔
      </span>
      <span class="spacer" />
      <span v-if="strokes.length" class="board__hint">
        {{ done ? '已画完本页' : '正在写…' }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.board {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.board__canvas {
  position: relative;
  flex: 1;
  margin: 14px;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
  overflow: hidden;
}

.board__canvas svg {
  width: 100%;
  height: 100%;
}

.board__empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
}

.board__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px 12px;
  font-size: 12px;
  color: var(--td-text-placeholder);
  flex-shrink: 0;
}

.board__bar .spacer {
  flex: 1;
}
</style>
