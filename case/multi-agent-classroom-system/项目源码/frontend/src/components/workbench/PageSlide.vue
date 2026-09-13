<script setup lang="ts">
/**
 * 幻灯片预览（版式照 `产品原型/workbench.html` 的 `.preview__slide`，16:9）。
 *
 * 只读：它显示的是**服务端那份** —— 编辑框里改了还没保存的内容不会先跑上来，
 * 「预览和实际不一致」比「预览慢半拍」难查得多。
 *
 * 讲稿（`narration`）也画在这里：讲台上看到的提示词和幻灯片是一体的，
 * 拆到两个面板反而要在两处对页号。
 */
import { computed } from 'vue'

import SourceBadge from '@/components/workbench/SourceBadge.vue'
import type { CoursePageItem, SlideDsl, SlideSource } from '@/types/api'
import { PAGE_KIND_LABELS, visualTypeLabel } from '@/utils/labels'

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
  }>(),
  { variant: 'workbench', activeSource: '', missingSources: () => [] },
)

const emit = defineEmits<{ openSource: [source: SlideSource] }>()

const dsl = computed<SlideDsl>(() => props.page?.dsl ?? {})
const narration = computed(() => dsl.value.narration ?? [])
/** 课堂舞台那一份不带工作台的侧栏提示 —— 那边根本没有「右侧」。 */
const onStage = computed(() => props.variant === 'classroom')

/** 这一页的出处（后端核对通过的才在里面）。课堂舞台不画徽标。 */
const sources = computed<SlideSource[]>(() => (onStage.value ? [] : dsl.value.sources ?? []))

/** 材料没覆盖到的子主题（P4-A8）：说出来，而不是让它编一段。 */
const gaps = computed<string[]>(() => (onStage.value ? [] : dsl.value.gaps ?? []))

const missingSet = computed(() => new Set(props.missingSources))

/**
 * 这一页那张画好的图。
 *
 * 老课程（P1 只出描述）没有 `svg`，这时退回原来的文字提示 —— 不假装有图，
 * 也不给一个空框子。导出那三份产物同一口径（`html._image_html`）。
 */
const figureSvg = computed(() => dsl.value.visual?.svg ?? '')

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
    <div v-if="page" class="preview__slide">
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
            <li v-for="(bullet, index) in dsl.bullets" :key="index">{{ bullet.text }}</li>
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

        <div v-if="dsl.visual" class="slide-visual" :class="{ 'has-figure': figureSvg }">
          <!--
            服务端画好的示意图（`generation.diagram` 的确定性产出，随 DSL 落库）。
            不是用户输入，也不是模型直接吐的 HTML —— 出图那一步只认结构化的
            `spec`，所以这里用 v-html 内联是安全的。
          -->
          <!-- eslint-disable-next-line vue/no-v-html -- 见上：内联的是服务端渲染好的 SVG -->
          <div v-if="figureSvg" class="slide-figure" v-html="figureSvg" />
          <!-- 有图时正文只留两行，全文挂 title 上（见 .slide-visual__desc 那条） -->
          <p class="slide-visual__desc" :title="figureSvg ? dsl.visual.desc : undefined">
            <span class="slide-visual__type">{{ visualTypeLabel(dsl.visual.type) }}</span>
            {{ dsl.visual.desc }}
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
      <p v-for="(beat, index) in narration" :key="index" class="beat">
        <span class="beat-no">{{ index + 1 }}</span>
        {{ beat.text }}
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
}

.preview__slide.is-empty {
  align-items: center;
  justify-content: center;
}

.slide-head {
  font-size: 12px;
  color: var(--td-brand-color);
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
  color: var(--td-text-secondary);
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
  background: var(--td-brand-color);
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
  font-family: var(--td-font-mono);
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
  background: var(--td-brand-color-light);
  border-radius: var(--td-radius-medium);
  padding: 16px 18px;
  font-size: 13px;
  color: var(--td-text-secondary);
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
  border: 1px solid var(--td-component-stroke);
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

.slide-visual__desc {
  margin: 0;
}

.slide-visual__type {
  color: var(--td-brand-color);
  font-family: var(--td-font-mono);
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
  color: var(--td-brand-color);
}

/* 出处那一行：贴着底部，不挤正文（正文用 flex 顶在上面） */
.slide-sources {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--td-component-stroke);
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
  color: var(--td-text-placeholder);
  padding-top: 12px;
  margin-top: auto;
  border-top: 1px solid var(--td-component-stroke);
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
