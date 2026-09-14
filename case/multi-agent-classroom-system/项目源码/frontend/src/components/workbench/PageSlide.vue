<script setup lang="ts">
/**
 * 幻灯片预览（版式照 `产品原型/workbench.html` 的 `.preview__slide`，16:9）。
 *
 * 只读：它显示的是**服务端那份** —— 编辑框里改了还没保存的内容不会先跑上来，
 * 「预览和实际不一致」比「预览慢半拍」难查得多。
 *
 * 讲稿（`narration`）也画在这里：讲台上看到的提示词和幻灯片是一体的，
 * 拆到两个面板反而要在两处对页号。
 *
 * 这一页的**交互**也在这里：可调参数的滑块与播放、以及跟着讲稿走的逐拍揭示。
 * 两条都按同一条纪律做 —— **不往图里塞脚本，也不在浏览器里重算一遍**：
 * 每一帧都是服务端预渲染好的 SVG（`visual.frames`），要揭示哪些元素也是
 * 服务端标好的（`data-beat`）。服务端那份是确定性的、与导出的 PDF/PPT 同源，
 * 前端要是自己算一遍，网页上和产出的课件就会是两个样子。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import SourceBadge from '@/components/workbench/SourceBadge.vue'
import type { CoursePageItem, ExportTemplate, SlideDsl, SlideSource } from '@/types/api'
import { PAGE_KIND_LABELS, visualTypeLabel } from '@/utils/labels'

/** 参数自己走一遍时，一帧停多久。太快看不清曲线怎么变的，太慢等得人心焦。 */
const FRAME_MS = 900

const props = withDefaults(
  defineProps<{
    page: CoursePageItem | null
    courseTitle: string
    pageCount: number
    /**
     * `classroom` = 课堂舞台那一份：只要幻灯片本体。
     * 讲稿在那边由字幕条承担，底下那句「右侧可改讲稿与标题」在课堂页也不成立。
     */
    variant?: 'workbench' | 'classroom'
    /** 抽屉里正显示着的那条出处（`materialId:chunkId`）。 */
    activeSource?: string
    /**
     * 原文已经取不到的出处（材料删了）：徽标画成失效态。
     *
     * 两种粒度：`materialId:chunkId`（这一段取不到）与 `materialId`
     * （整份材料没了）—— 见 `MaterialDrawer` 的 `missing` 事件。
     */
    missingSources?: string[]
    /**
     * 讲稿讲到这一页的第几拍（`p{页号}-b{序号}` 里的那个序号）。
     *
     * `null` = **不要揭示**，整张图一次全显示：工作台预览是这样（编辑时没有
     * 「讲到哪了」这回事），课堂里这一页还没开讲时也是这样。给了数就按拍揭示 ——
     * 服务端在图上标了 `data-beat`（`generation.diagram` 给每条边、每个节点
     * 标的），这里只负责把还没讲到的那些藏起来。
     */
    beat?: number | null
    /**
     * 课程选定的 PPT 模板（配色 / 字体 / 版式），来自 `/api/capabilities`。
     *
     * 给了就照着换色、按 `layout` 换页眉页脚的版式，与三个导出渲染器同源
     * （`exports/theme.py`）；为 null（老课程 / 清单没拉到）就用 TDesign 默认样式。
     */
    theme?: ExportTemplate | null
  }>(),
  {
    variant: 'workbench',
    activeSource: '',
    missingSources: () => [],
    beat: null,
    theme: null,
  },
)

const emit = defineEmits<{ openSource: [source: SlideSource] }>()

/**
 * 一套模板令牌 → 幻灯片上的 CSS 变量（`--sl-*`）。
 *
 * 每个变量在样式里都带 TDesign 兜底（`var(--sl-brand, var(--td-brand-color))`），
 * 所以 `theme` 为 null 时预览就是原来那个样子；给了 theme 才照着换色换字体 ——
 * 与导出同源，避免「预览一个样、导出另一个样」。变量只挂在 `.preview__slide`
 * 上，下方的讲稿 / 出处提示那些工作台壳子不受影响（它们不属于幻灯片）。
 */
const slideStyle = computed<Record<string, string>>(() => {
  const theme = props.theme
  if (!theme) return {}
  const style: Record<string, string> = {}
  const colors = theme.colors
  if (colors) {
    if (colors.brand) {
      style['--sl-brand'] = colors.brand
      // 图示那块底色是品牌色的淡色版：没对应令牌，用 color-mix 现调一个。
      style['--sl-brand-light'] = `color-mix(in srgb, ${colors.brand} 10%, #fff)`
    }
    if (colors.ink) style['--sl-ink'] = colors.ink
    if (colors.muted) style['--sl-muted'] = colors.muted
    if (colors.line) style['--sl-line'] = colors.line
    if (colors.warn) style['--sl-warn'] = colors.warn
  }
  const fonts = theme.fonts
  if (fonts) {
    if (fonts.sans) style['--sl-sans'] = fonts.sans
    if (fonts.mono) style['--sl-mono'] = fonts.mono
  }
  return style
})

/** 版式档位：认不出的值当 `classic`（与三个渲染器同一条兜底）。 */
const layout = computed(() => {
  const value = props.theme?.layout
  return value === 'swiss' || value === 'tech' ? value : 'classic'
})

const dsl = computed<SlideDsl>(() => props.page?.dsl ?? {})
const narration = computed(() => dsl.value.narration ?? [])
/** 课堂舞台那一份不带工作台的侧栏提示 —— 那边根本没有「右侧」。 */
const onStage = computed(() => props.variant === 'classroom')

/** 这一页的出处（后端核对通过的才在里面）。课堂舞台不画徽标。 */
const sources = computed<SlideSource[]>(() => (onStage.value ? [] : dsl.value.sources ?? []))

/** 材料没覆盖到的子主题（P4-A8）：说出来，而不是让它编一段。 */
const gaps = computed<string[]>(() => (onStage.value ? [] : dsl.value.gaps ?? []))

const missingSet = computed(() => new Set(props.missingSources))

const visual = computed(() => dsl.value.visual ?? null)

/**
 * 服务端预渲染的每一帧。只有「带 params 的曲线图」才有；别的图这里是空表，
 * 滑块那一行也就不出现。
 */
const frames = computed(() => visual.value?.frames ?? [])
const param = computed(() => visual.value?.params ?? null)
const hasFrames = computed(() => frames.value.length > 1)

const frameIndex = ref(0)

/**
 * 这一页那张画好的图。
 *
 * **有可调参数时显示的是当前那一帧**，没有就是服务端随 DSL 存下来的那张
 * （`visual.svg`）。两者是同一套画法排出来的 —— 拖动滑块不重新渲染，只是
 * 换一张已经画好的图，所以拖动时不会闪、也不会和导出对不上。
 *
 * 老课程（P1 只出描述）没有 `svg`，这时退回原来的文字提示 —— 不假装有图，
 * 也不给一个空框子。导出那三份产物同一口径（`html._image_html`）。
 */
const figureSvg = computed(() => {
  const list = frames.value
  if (list.length) return list[frameIndex.value]?.svg ?? ''
  return visual.value?.svg ?? ''
})

/** 滑块右边显示的那个数 —— 显示**参数值**而不是帧序号：「k = 2」才有意义。 */
const paramValue = computed(() => frames.value[frameIndex.value]?.value ?? '')

const playing = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

function stopPlay() {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
  playing.value = false
}

/**
 * 让参数自己从一头走到另一头。
 *
 * 走到头就停，**不循环**：这条是「演示一遍这个参数在干什么」，不是让它一直转。
 * 从最后一帧按下去会先回到第一帧再走 —— 讲完一遍想再来一遍，不用先把滑块拖回去。
 */
function togglePlay() {
  if (playing.value) {
    stopPlay()
    return
  }
  const last = frames.value.length - 1
  if (last < 1) return
  if (frameIndex.value >= last) frameIndex.value = 0
  playing.value = true
  timer = setInterval(() => {
    if (frameIndex.value >= last) {
      stopPlay()
      return
    }
    frameIndex.value += 1
  }, FRAME_MS)
}

/** 拖动滑块：**先停播放**，否则松手之后它还会自己接着往前跑。 */
function onScrub(value: number | number[]) {
  if (typeof value !== 'number') return
  stopPlay()
  frameIndex.value = value
}

/** 老师用讲台翻页时，参数回到初始那一帧 —— 停在上一次的取值上会让人以为看错了图。 */
watch(
  () => props.page,
  () => {
    stopPlay()
    frameIndex.value = 0
  },
)

onBeforeUnmount(stopPlay)

// --- 逐拍揭示 ---

/** 图上那一层容器：`data-beat` 的元素都在它里面。 */
const figureEl = ref<HTMLElement | null>(null)

/**
 * 揭示到图的第几层。
 *
 * `data-beat` 是**图自己的层号**（`diagram` 标的行号），不是讲稿的拍号 ——
 * 一张五行的图和这一页的三拍对不上。所以最后一拍**一律整张全显示**：
 * 不这么兜一下，比拍数多的那几层永远轮不到，图是残的。
 * 中间那些拍按层号一一兑现，就是「讲到哪儿长到哪儿」。
 */
const shownUpTo = computed(() => {
  const beat = props.beat
  if (beat === null) return Number.POSITIVE_INFINITY
  if (beat >= narration.value.length - 1) return Number.POSITIVE_INFINITY
  return beat
})

/**
 * 把还没讲到的元素藏起来。
 *
 * 藏的是**服务端标了 `data-beat` 的元素**（流程图的每条边、每个节点）。
 * 这件事只能在这一层做：`ir._svg_of` 会拒掉带 `on*=` 的 SVG，图上挂不了脚本，
 * 所以揭示的时机由 Vue 按讲稿的拍子推。公式和曲线图没有 `data-beat` ——
 * 它们的交互是滑块，这里查不到东西就什么都不动。
 *
 * `beat` 为 `null`（工作台预览、这一页还没开讲）时一律显示，不看标记。
 */
function applyReveal() {
  const host = figureEl.value
  if (!host) return
  const upTo = shownUpTo.value
  host.classList.toggle('is-revealing', Number.isFinite(upTo))
  for (const mark of host.querySelectorAll<SVGElement>('[data-beat]')) {
    const at = Number(mark.dataset.beat)
    mark.classList.toggle('is-on', !Number.isFinite(upTo) || !Number.isFinite(at) || at <= upTo)
  }
}

/*
 * 三个来源都要看：
 * - `figureSvg` 换了（翻页、换帧）就得在一张**新**的图上重新点一遍标记；
 * - `shownUpTo` 往前走了一拍（不是 `props.beat`：兜底那一下也在它里面）；
 * - 容器刚挂上来（`figureEl` 从 null 变成元素）—— 只盯前两个的话，第一次
 *   画出来的那一张会一直是全亮的，要等到下一拍才追上。
 *
 * `flush: 'post'` 是关键：要等这次重排落地、DOM 里真的是新那张图了再去点，
 * 早一步点的是上一张图里的元素，翻页时会露出一整张没揭示的图。
 */
watch([figureSvg, shownUpTo, figureEl], applyReveal, { flush: 'post', immediate: true })

/** 正文里有没有「字」那一摊（要点/代码/题目/辩题）。 */
const hasText = computed(() => {
  const d = dsl.value
  return Boolean(
    d.bullets?.length || d.code || d.quiz || d.question || d.topic || d.sides?.length,
  )
})

/**
 * 正文分不分左右两栏。
 *
 * 只有「有图**又有**字」才分。整页只有图的时候不分 —— 分开就是图占一半、
 * 空一半（导出那边同理：`pptx._body` 只有图上文字时才会摆右栏）。
 */
const split = computed(() => Boolean(figureSvg.value) && hasText.value)

const keyOf = (source: SlideSource) => `${source.materialId}:${source.chunkId}`

/**
 * 这条出处还打不开吗。
 *
 * 整份材料被删时抽屉报的是材料那一级（它也不知道这一页引的是哪几段），
 * 所以两个键都要看 —— 少看一个，页面上就会留一个点得动、点开却是空的徽标。
 */
const isMissing = (source: SlideSource) =>
  missingSet.value.has(keyOf(source)) || missingSet.value.has(source.materialId)
</script>

<template>
  <div class="page-slide" :class="{ 'is-stage': onStage }">
    <div v-if="page" class="preview__slide" :style="slideStyle" :data-layout="layout">
      <div class="slide-head">
        第 {{ page.pageNo }} 页 · {{ PAGE_KIND_LABELS[page.kind] }}
      </div>
      <h3 class="slide-title">
        {{ dsl.title }}
        <small v-if="dsl.subtitle">{{ dsl.subtitle }}</small>
      </h3>

      <!--
        正文分两栏：**有图又有字的时候左右分**（图在左、字在右），别的页还是一列。
        这不是新发明的版式，是把导出的 PPTX 那一份搬过来（`exports/pptx.py` 的
        `_body`：图和字本来就分左右两栏）—— 预览和产物长得一样，才谈得上「所见即所得」。
      -->
      <div class="slide-body" :class="{ 'is-split': split }">
        <div v-if="hasText" class="slide-text">
          <ul v-if="dsl.bullets?.length" class="slide-bullets">
            <li v-for="(bullet, index) in dsl.bullets" :key="index">
              <!--
                要点里的行内公式（`$…$`）：服务端已经排好成 SVG 了（见后端
                `schema._inline_pieces`），这里按块贴进去就行 —— 浏览器不认
                LaTeX，在这里现画就得再写一个排版引擎，网页和 PDF 也迟早分叉。
                `pieces` 是拼得回整句的，所以不走 `bullet.text`（那上面还带着 `$`）。
              -->
              <template v-if="bullet.pieces?.length">
                <template v-for="(piece, at) in bullet.pieces" :key="at">
                  <!-- eslint-disable-next-line vue/no-v-html -- 内联的是服务端渲染好的 SVG，不是模型吐的 HTML -->
                  <span v-if="piece.kind === 'math' && piece.svg" class="math" v-html="piece.svg" />
                  <template v-else>{{ piece.text }}</template>
                </template>
              </template>
              <template v-else>{{ bullet.text }}</template>
            </li>
          </ul>

          <div v-if="dsl.code" class="slide-code">
            <pre>{{ dsl.code.content }}</pre>
            <span v-if="dsl.code.lang" class="slide-code__lang">{{ dsl.code.lang }}</span>
          </div>

          <div v-if="dsl.quiz" class="slide-quiz">
            <p class="quiz-stem">{{ dsl.quiz.stem }}</p>
            <ol class="quiz-options">
              <li v-for="(option, index) in dsl.quiz.options" :key="index">{{ option }}</li>
            </ol>
          </div>

          <p v-if="dsl.question" class="slide-question">{{ dsl.question }}</p>
          <p v-if="dsl.topic" class="slide-question">{{ dsl.topic }}</p>
          <ul v-if="dsl.sides?.length" class="slide-bullets">
            <li v-for="(side, index) in dsl.sides" :key="index">{{ side.stance }}</li>
          </ul>
        </div>

        <div v-if="visual" class="slide-visual" :class="{ 'has-figure': figureSvg }">
          <!--
            服务端画好的示意图（`generation.diagram` 的确定性产出，随 DSL 落库）。
            不是用户输入，也不是模型直接吐的 HTML —— 出图那一步只认结构化的
            `spec`，所以这里用 v-html 内联是安全的。
          -->
          <!-- eslint-disable-next-line vue/no-v-html -- 见上：内联的是服务端渲染好的 SVG -->
          <div v-if="figureSvg" ref="figureEl" class="slide-figure" v-html="figureSvg" />

          <!--
            可调参数：拖滑块换一帧，或者让参数自己走一遍（见上面 `togglePlay`）。
            只对带 `params` 的曲线图出现 —— 流程图和公式没有参数，这一行就没有。
          -->
          <div v-if="hasFrames" class="slide-param">
            <span class="slide-param__label">{{ param?.label || param?.name }}</span>
            <t-slider
              class="slide-param__slider"
              :model-value="frameIndex"
              :min="0"
              :max="frames.length - 1"
              :step="1"
              :label="false"
              @update:model-value="onScrub"
            />
            <span class="slide-param__value">{{ paramValue }}</span>
            <button
              type="button"
              class="slide-param__play"
              :title="playing ? '停下' : '让参数自己走一遍'"
              @click="togglePlay"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <template v-if="playing">
                  <path d="M9 6v12M15 6v12" />
                </template>
                <path v-else d="M8 5l11 7-11 7z" />
              </svg>
            </button>
          </div>

          <!-- 有图时正文只留两行，全文挂 title 上（见 .slide-visual__desc 那条） -->
          <p class="slide-visual__desc" :title="figureSvg ? visual.desc : undefined">
            <span class="slide-visual__type">{{ visualTypeLabel(visual.type) }}</span>
            {{ visual.desc }}
          </p>
        </div>
      </div>

      <!-- 出处（P4-A6）：这一页的每一条都写出来，点一下去抽屉看原文 -->
      <div v-if="sources.length" class="slide-sources">
        <span class="slide-sources__label">出处</span>
        <SourceBadge
          v-for="source in sources"
          :key="keyOf(source)"
          :source="source"
          :active="keyOf(source) === activeSource"
          :missing="isMissing(source)"
          @open="emit('openSource', $event)"
        />
      </div>

      <div class="slide-foot">
        <span>{{ courseTitle }} · EduAgentX</span>
        <span>{{ String(page.pageNo).padStart(2, '0') }} / {{ pageCount }}</span>
      </div>
    </div>

    <div v-else class="preview__slide is-empty">
      <t-empty title="还没有可预览的页面" description="在左边的大纲里选一页" />
    </div>

    <div v-if="gaps.length || dsl.sourceMissing" class="slide-flags">
      <p v-if="dsl.sourceMissing" class="slide-flags__row">
        <t-tag theme="warning" variant="light" size="small">出处对不上</t-tag>
        这一页有引文在材料里核对不上，内容已保留，建议核对或重写这一页。
      </p>
      <p v-for="(gap, index) in gaps" :key="index" class="slide-flags__row">
        <t-tag theme="warning" variant="light" size="small">材料没写</t-tag>
        {{ gap }}
      </p>
    </div>

    <div v-if="narration.length && !onStage" class="slide-notes">
      <h5>讲稿</h5>
      <p v-for="(line, index) in narration" :key="index" class="beat">
        <span class="beat-no">{{ index + 1 }}</span>
        {{ line.text }}
      </p>
    </div>

    <div v-if="!onStage" class="preview__hint">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8h.01M12 11v5" />
      </svg>
      预览为只读 · 显示的是服务端已保存的那一版，右侧可改讲稿与标题
    </div>
  </div>
</template>

<style scoped>
/* 版式取自 产品原型/workbench.html 的 .preview */
/*
 * 工作台那一份：**宽度吃满这一格**，只按高度封顶。
 *
 * 不封宽度是有意的。幻灯片的高度是宽度算出来的（16:9），所以宽度是这一列里
 * 唯一「能自己长」的东西 —— 给它一个定值（比如 960），中间的编辑区一旦比
 * 它宽，多出来的部分就变成 PPT 右边的一块空白；下面的讲稿、出处都跟着这张
 * 卡片走，于是整列右边空一条。让它 `flex: 1` 铺满，那一块就不存在了。
 *
 * 要防的是另一头：宽度一涨高度跟着涨，矮屏上不讲上限就会把讲稿、出处、提示
 * 顶出可视区，整栏开始滚 —— 那反而看不全一页。所以按剩余高度反推宽度
 * （300 ≈ 壳顶栏 60 + 工具条 49 + 上下留白 40 + 讲稿与出处 150）。
 */
.page-slide {
  flex: 1;
  min-width: 0;
  max-width: calc((100vh - 300px) * 16 / 9);
}

/*
 * 课堂舞台那一份：外框由它自己定（同样 16:9、同样 960 上限），
 * 因为舞台里没有 `.preview__slide` 那一层同尺寸的容器可以借。
 */
.page-slide.is-stage {
  flex: none;
  width: 100%;
  max-width: 960px;
  aspect-ratio: 16 / 9;
  display: flex;
}

.page-slide.is-stage .preview__slide {
  flex: 1;
  box-shadow: var(--td-shadow-2);
}

.preview__slide {
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
  aspect-ratio: 16 / 9;
  padding: 36px 44px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--sl-ink, var(--td-text-primary));
  font-family: var(--sl-sans, var(--td-font-family));
}

.preview__slide.is-empty {
  align-items: center;
  justify-content: center;
}

.slide-head {
  font-size: 12px;
  color: var(--sl-brand, var(--td-brand-color));
  font-weight: 600;
  letter-spacing: 2px;
  margin-bottom: 8px;
}

.slide-title {
  font-size: 24px;
  font-weight: 600;
}

.slide-title small {
  display: block;
  font-size: 13px;
  color: var(--sl-muted, var(--td-text-secondary));
  font-weight: 400;
  margin-top: 6px;
}

/*
 * 正文。
 *
 * 默认还是一列（要点在上、图在下）。`is-split` 是本页**有图又有字** ——
 * 左右两栏，图在左、字在右。
 *
 * 为什么要分：幻灯片是 16:9 的定屏，一列排下来「5 条要点 + 图 + 图说 + 出处」
 * 的高度必定超过屏高，flex 一收缩，吃亏的是 `overflow-y: auto` 的要点
 * —— 它会被压到半行，读起来就像被图盖住了。分成两栏之后，图和字各有各的
 * 高度，谁也不挤谁。这也是导出的 PPTX 一直在用的版式（`exports/pptx.py`
 * 的 `_body`），预览跟产物对上，才算所见即所得。
 */
.slide-body {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
}

.slide-body.is-split {
  /* 图那一栏在 DOM 里排在字后面，row-reverse 把它摆到左边 */
  flex-direction: row-reverse;
  align-items: stretch;
  gap: 20px;
}

.slide-text {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
}

.slide-body.is-split .slide-text {
  flex: 1 1 46%;
}

.slide-bullets {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 22px;
  font-size: 14px;
  line-height: 1.7;
  overflow-y: auto;
}

.slide-bullets li {
  list-style: none;
  padding-left: 18px;
  position: relative;
}

.slide-bullets li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  width: 7px;
  height: 7px;
  border-radius: 2px;
  background: var(--sl-brand, var(--td-brand-color));
}

/*
 * 要点里那截公式（服务端排好的 SVG，`v-html` 进来的）。
 *
 * 它自带 `width`/`height` 和一条 `vertical-align`（那个负偏移量是按自己的
 * 基线深度算出来的，见后端 `formula.inline_metrics`）—— 这里只把 `display`
 * 补上：SVG 默认是 `inline`，跟汉字混排时行高会跳。
 */
.slide-bullets :deep(.math svg) {
  display: inline-block;
}

.slide-code {
  position: relative;
  margin-top: 18px;
  background: var(--td-bg-secondary-container);
  border-radius: var(--td-radius-default);
  padding: 12px 16px;
  overflow: auto;
}

.slide-code pre {
  font-family: var(--sl-mono, var(--td-font-mono));
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.slide-code__lang {
  position: absolute;
  top: 6px;
  right: 10px;
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.slide-visual {
  margin-top: 18px;
  background: var(--sl-brand-light, var(--td-brand-color-light));
  border-radius: var(--td-radius-medium);
  padding: 16px 18px;
  font-size: 13px;
  color: var(--sl-muted, var(--td-text-secondary));
  display: flex;
  gap: 10px;
}

/*
 * 有图时这一块改竖排，并且**吃掉正文剩下的高度**：幻灯片是 16:9 的定屏，
 * 960px 宽的图按原比例排下来比整页还高，必须让它按剩余空间缩。
 * `min-height: 0` 是关键 —— 不写它，flex 子项不会缩到内容尺寸以下。
 */
.slide-visual.has-figure {
  flex: 1 1 auto;
  min-height: 0;
  flex-direction: column;
  gap: 8px;
  background: transparent;
  padding: 0;
}

/* 两栏时图那一栏要吃满整列高：图说在上面顶掉的那点高度，从图身上出 */
.slide-body.is-split .slide-visual {
  flex: 1 1 54%;
  min-width: 0;
  margin-top: 0;
}

/*
 * 有图时，图说压到两行以内。
 *
 * 它是「这张图讲什么」的一句注，不是课文 —— 讲稿里有的是话。而图上下的空间
 * 是共享的：注多一行，图就小一圈，四十几字的注铺下来能把图压成缩略图。
 * 留两行加省略号，全文挂在 `title` 上（悬停可看）。
 */
.slide-visual.has-figure .slide-visual__desc {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
}

.slide-figure {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--td-bg-container);
  border: 1px solid var(--sl-line, var(--td-component-stroke));
  border-radius: var(--td-radius-medium);
  overflow: hidden;
}

/* SVG 自带 width/height 属性；这里让它按可用空间等比缩放（宽高都 auto）。 */
.slide-figure :deep(svg) {
  display: block;
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
}

/*
 * 逐拍揭示。
 *
 * 只在**真的在揭示**（容器上有 `.is-revealing`，即当前有讲稿拍子）时才藏 ——
 * 工作台预览那一份不带这个类，整张图一次全显示，跟导出的课件长得一样。
 *
 * 藏的是服务端标了 `data-beat` 的元素（流程图的边与节点）。公式和曲线图没有
 * 这个标记，选中不到任何元素，这段样式对它们不生效。
 */
.slide-figure.is-revealing :deep([data-beat]) {
  opacity: 0;
  transition: opacity 0.35s ease;
}

.slide-figure.is-revealing :deep([data-beat].is-on) {
  opacity: 1;
}

/*
 * 流程图「动起来」：边上的线做成流动虚线，一眼看出「谁流向谁」。
 *
 * 只活在**能跑 CSS 的地方**（工作台 / 课堂实时预览）。导出 PPTX / PDF 取的是
 * 静态栅格帧，这段样式不会跟过去 —— 发出去的课件不该自己动。
 * 钩子是服务端在 SVG 上打的 `class="dg-edge"`（`generation.diagram`）。
 */
.slide-figure :deep(.dg-edge path) {
  stroke-dasharray: 7 5;
  animation: dg-flow 1.1s linear infinite;
}

@keyframes dg-flow {
  to {
    stroke-dashoffset: -12;
  }
}

/* 系统开了「减弱动态效果」就别动 —— 流动虚线对前庭敏感的人是负担。 */
@media (prefers-reduced-motion: reduce) {
  .slide-figure :deep(.dg-edge path) {
    animation: none;
  }
}

/*
 * 可调参数那一行：参数名 · 滑块 · 当前值 · 播放。
 *
 * 值那一格给固定宽度是有意的 —— 不定宽的话，k 从 2 走到 -1 位数一变，
 * 滑块就会被推得左右挪一下，正在拖的时候手感很差。
 */
.slide-param {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12.5px;
  color: var(--td-text-secondary);
}

.slide-param__label {
  font-family: var(--sl-mono, var(--td-font-mono));
  color: var(--sl-brand, var(--td-brand-color));
  flex-shrink: 0;
}

.slide-param__slider {
  flex: 1 1 auto;
  min-width: 0;
}

.slide-param__value {
  font-family: var(--sl-mono, var(--td-font-mono));
  min-width: 44px;
  text-align: right;
  flex-shrink: 0;
}

.slide-param__play {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--sl-line, var(--td-component-stroke));
  border-radius: 50%;
  background: var(--td-bg-container);
  color: var(--sl-brand, var(--td-brand-color));
  cursor: pointer;
}

.slide-param__play:hover {
  border-color: var(--sl-brand, var(--td-brand-color));
}

.slide-param__play svg {
  width: 13px;
  height: 13px;
  fill: currentColor;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
}

.slide-visual__desc {
  margin: 0;
}

.slide-visual__type {
  color: var(--sl-brand, var(--td-brand-color));
  font-family: var(--sl-mono, var(--td-font-mono));
  font-size: 12px;
}

.slide-quiz {
  margin-top: 18px;
  font-size: 14px;
}

.quiz-stem {
  font-weight: 500;
}

.quiz-options {
  margin-top: 8px;
  padding-left: 20px;
  color: var(--td-text-secondary);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.slide-question {
  margin-top: 14px;
  font-size: 14px;
  color: var(--sl-brand, var(--td-brand-color));
}

/* 出处那一行：贴着底部，不挤正文（正文用 flex 顶在上面） */
.slide-sources {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--sl-line, var(--td-component-stroke));
}

.slide-sources__label {
  font-size: 11.5px;
  color: var(--td-text-placeholder);
}

.slide-flags {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.slide-flags__row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--td-text-secondary);
  background: var(--td-warning-color-light);
  border-radius: var(--td-radius-default);
  padding: 6px 10px;
}

.slide-foot {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--sl-muted, var(--td-text-placeholder));
  padding-top: 12px;
  margin-top: auto;
  border-top: 1px solid var(--sl-line, var(--td-component-stroke));
}

/*
 * 版式微调：三档 layout 给页眉 / 标题 / 页脚不同的样子 —— 与三个导出渲染器
 * 同源（`exports/html.py` 的 `[data-layout=…]`、`exports/pptx.py` 的 `_header_decor`）。
 * 正文主体的排布三档一致，换的只是「封面与页眉页脚那一圈」。classic 就是上面
 * 那套默认样子，不额外写。
 */
[data-layout='swiss'] .slide-head {
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-weight: 700;
}

[data-layout='swiss'] .slide-title {
  font-size: 28px;
  letter-spacing: -0.5px;
}

/* 瑞士：标题下压一道品牌色横线（对应 html 的 `.slide__head::after`）。 */
[data-layout='swiss'] .slide-title::after {
  content: '';
  display: block;
  width: 100%;
  height: 3px;
  margin-top: 10px;
  background: var(--sl-brand, var(--td-brand-color));
}

[data-layout='swiss'] .slide-foot span:last-child {
  color: var(--sl-brand, var(--td-brand-color));
  font-weight: 700;
}

/* 科技青：标题带一道竖向强调条（对应 pptx 的 `_bar`）。 */
[data-layout='tech'] .slide-title {
  font-size: 22px;
  border-left: 4px solid var(--sl-brand, var(--td-brand-color));
  padding-left: 12px;
}

[data-layout='tech'] .slide-foot span:last-child {
  border: 1px solid var(--sl-line, var(--td-component-stroke));
  border-radius: 8px;
  padding: 0 8px;
}

.slide-notes {
  margin-top: 14px;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
  padding: 14px 18px;
}

.slide-notes h5 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

.slide-notes .beat {
  font-size: 13px;
  line-height: 1.8;
  color: var(--td-text-secondary);
}

.slide-notes .beat-no {
  display: inline-block;
  min-width: 18px;
  color: var(--td-text-placeholder);
  font-family: var(--td-font-mono);
  font-size: 11px;
}

.preview__hint {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.preview__hint svg {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}
</style>
