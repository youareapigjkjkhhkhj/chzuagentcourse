<script setup lang="ts">
/**
 * 大纲树（版式照 `产品原型/workbench.html` 的 `.tree-chapter` / `.tree-page`）。
 *
 * 四态（P1-A4）里只有三个来自 REST：`ready` 完成、`failed` 失败、`pending` 待生成。
 * 「生成中」是**正在写的那一页**，由 SSE 的 `step.progress` 实时给（`livePageNo`）；
 * 「编辑中」是用户当前选中的那一页。服务端因此不需要每次写页都改一次树 ——
 * 树只在大纲真的变了的时候才动。
 *
 * 这一层只管画与手势，**不动树**：折叠是本地状态（纯视图），增删改序一律
 * emit 给页面（那边有 `useOutlineDraft`）。所以网格上看到的这棵树与即将提交的
 * 那棵树永远是同一棵。
 *
 * 开篇（封面 / 大纲页）与收尾（小结）**没有拖柄、没有删除、没有加页**：它们由
 * 管线按规则补齐，提交时也会被服务端摘掉重排（`intake.clean_outline`），
 * 在它们身上做的任何编辑都会石沉大海 —— 与其做个点了没反应的按钮，不如不做。
 */
import { computed, ref } from 'vue'

import type { OutlineChapter, OutlinePageItem, OutlineTree } from '@/types/api'
import { PAGE_STATE_LABELS, PAGE_STATE_THEMES, type PageState } from '@/utils/labels'

const props = withDefaults(
  defineProps<{
    tree: OutlineTree
    selectedNo: number
    livePageNo: number
    readyPages: number[]
    /**
     * 能不能改（增删改序）。
     *
     * 只有停在大纲确认点时才为真：生成跑起来之后服务端不再受理大纲
     * （`ensure_confirmable` 一律 409，「这次生成已经结束，大纲不能再改」），
     * 那时候还能删页的按钮就是个陷阱 —— 删了没处提交。
     */
    editable?: boolean
  }>(),
  { editable: false },
)

const emit = defineEmits<{
  select: [pageNo: number]
  remove: [payload: { chapterNo: number; pageNo: number }]
  'add-page': [chapterNo: number]
  move: [payload: { pageNo: number; overPageNo: number }]
}>()

function stateOf(item: OutlinePageItem): PageState {
  if (item.pageNo === props.selectedNo) return 'editing'
  if (item.status === 'failed') return 'failed'
  if (item.status === 'ready' || props.readyPages.includes(item.pageNo)) return 'ready'
  if (props.livePageNo > 0 && item.pageNo === props.livePageNo) return 'generating'
  return 'pending'
}

function remove(chapter: OutlineChapter, item: OutlinePageItem): void {
  emit('remove', { chapterNo: chapter.no, pageNo: item.pageNo })
}

/* --- 折叠：纯粹是「这一屏上画不画」，与树本身无关 --- */

const collapsed = ref<number[]>([])

function toggle(no: number): void {
  collapsed.value = collapsed.value.includes(no)
    ? collapsed.value.filter((item) => item !== no)
    : [...collapsed.value, no]
}

const isOpen = (no: number) => !collapsed.value.includes(no)

/**
 * 页号这一列画的是**位置**（整门课里第几页），不是 `item.pageNo`。
 *
 * 平时两者相等；一旦拖动过，服务端那个页号就还是旧的 —— 那时候屏幕上写着
 * 「4」而它排在第三位，比不写还难懂。位置是这一列唯一想说清的事，
 * 真正的页号在右边预览的标签上。
 */
const positions = computed(() => {
  const map = new Map<number, number>()
  let no = props.tree.front.length
  for (const chapter of props.tree.chapters) {
    for (const item of chapter.pages) {
      no += 1
      map.set(item.pageNo, no)
    }
  }
  return map
})

/* --- 拖动排序：只认正文页，落点决定它归哪一章 --- */

const draggingNo = ref(0)
const overNo = ref(0)

function startDrag(event: DragEvent, item: OutlinePageItem): void {
  draggingNo.value = item.pageNo
  // Firefox 不在 dataTransfer 上放点东西就不触发 drop
  event.dataTransfer?.setData('text/plain', String(item.pageNo))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function drop(item: OutlinePageItem): void {
  const from = draggingNo.value
  draggingNo.value = 0
  overNo.value = 0
  if (!from || from === item.pageNo) return
  emit('move', { pageNo: from, overPageNo: item.pageNo })
}

function endDrag(): void {
  draggingNo.value = 0
  overNo.value = 0
}
</script>

<template>
  <div class="wb-tree">
    <!-- 开篇：封面与大纲页。系统页，只读（页号用 -1 当折叠的 key，不会撞上章号） -->
    <div
      v-if="tree.front.length"
      class="tree-chapter"
      :class="{ 'is-open': isOpen(-1) }"
    >
      <div
        class="tree-chapter__title"
        title="封面与大纲页由系统生成，不参与提交"
        @click="toggle(-1)"
      >
        <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 6l6 6-6 6" />
        </svg>
        <span class="tree-chapter__name">开篇</span>
        <span class="text-placeholder chapter-count">{{ tree.front.length }} 页</span>
      </div>
      <div v-if="isOpen(-1)" class="tree-chapter__pages">
        <div
          v-for="item in tree.front"
          :key="item.pageNo"
          class="tree-page"
          :class="{ 'is-selected': item.pageNo === selectedNo }"
          @click="emit('select', item.pageNo)"
        >
          <span class="p-title">{{ item.title }}</span>
          <span class="p-status">
            <t-tag :theme="PAGE_STATE_THEMES[stateOf(item)]" variant="light" size="small">
              {{ PAGE_STATE_LABELS[stateOf(item)] }}
            </t-tag>
          </span>
        </div>
      </div>
    </div>

    <!-- 正文各章：可折叠 / 拖序 / 增页 / 删页 -->
    <div
      v-for="chapter in tree.chapters"
      :key="chapter.no"
      class="tree-chapter"
      :class="{ 'is-open': isOpen(chapter.no) }"
    >
      <div class="tree-chapter__title" @click="toggle(chapter.no)">
        <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 6l6 6-6 6" />
        </svg>
        <span class="tree-chapter__name">{{ chapter.title }}</span>
        <span class="text-placeholder chapter-count">{{ chapter.pages.length }} 页</span>
        <button
          v-if="editable"
          class="tree-chapter__add"
          title="在这一章末尾加一页"
          @click.stop="emit('add-page', chapter.no)"
        >
          + 页
        </button>
      </div>
      <div v-if="isOpen(chapter.no)" class="tree-chapter__pages">
        <div
          v-for="item in chapter.pages"
          :key="item.pageNo"
          class="tree-page"
          :class="{
            'is-selected': item.pageNo === selectedNo,
            'is-dragging': draggingNo === item.pageNo,
            'is-over': overNo === item.pageNo,
          }"
          :draggable="editable"
          :title="editable ? '按住拖到别的位置可以调整顺序' : ''"
          @click="emit('select', item.pageNo)"
          @dragstart="startDrag($event, item)"
          @dragover.prevent="overNo = item.pageNo"
          @drop.prevent="drop(item)"
          @dragend="endDrag"
        >
          <svg v-if="editable" class="drag" viewBox="0 0 24 24" fill="currentColor">
            <circle cx="9" cy="6" r="1.5" />
            <circle cx="15" cy="6" r="1.5" />
            <circle cx="9" cy="12" r="1.5" />
            <circle cx="15" cy="12" r="1.5" />
            <circle cx="9" cy="18" r="1.5" />
            <circle cx="15" cy="18" r="1.5" />
          </svg>
          <span class="p-no mono">{{ positions.get(item.pageNo) }}</span>
          <span class="p-title">{{ item.title }}</span>
          <span class="p-status">
            <t-tag :theme="PAGE_STATE_THEMES[stateOf(item)]" variant="light" size="small">
              {{ PAGE_STATE_LABELS[stateOf(item)] }}
            </t-tag>
          </span>
          <button
            v-if="editable"
            class="tree-page__del"
            title="从大纲里删掉这一页"
            @click.stop="remove(chapter, item)"
          >
            ×
          </button>
        </div>
      </div>
    </div>

    <!-- 收尾：小结页。同样只读 -->
    <div v-if="tree.back.length" class="tree-chapter" :class="{ 'is-open': isOpen(-2) }">
      <div
        class="tree-chapter__title"
        title="小结页由系统生成，不参与提交"
        @click="toggle(-2)"
      >
        <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 6l6 6-6 6" />
        </svg>
        <span class="tree-chapter__name">收尾</span>
        <span class="text-placeholder chapter-count">{{ tree.back.length }} 页</span>
      </div>
      <div v-if="isOpen(-2)" class="tree-chapter__pages">
        <div
          v-for="item in tree.back"
          :key="item.pageNo"
          class="tree-page"
          :class="{ 'is-selected': item.pageNo === selectedNo }"
          @click="emit('select', item.pageNo)"
        >
          <span class="p-title">{{ item.title }}</span>
          <span class="p-status">
            <t-tag :theme="PAGE_STATE_THEMES[stateOf(item)]" variant="light" size="small">
              {{ PAGE_STATE_LABELS[stateOf(item)] }}
            </t-tag>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 版式取自 产品原型/workbench.html */
.wb-tree {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.tree-chapter {
  margin-bottom: 8px;
}

.tree-chapter__title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  font-size: 13.5px;
  font-weight: 600;
  border-radius: var(--td-radius-default);
  cursor: pointer;
}

.tree-chapter__title:hover {
  background: var(--td-bg-container-hover);
}

.tree-chapter__title .arrow {
  width: 14px;
  height: 14px;
  color: var(--td-text-placeholder);
  transition: transform 0.2s;
}

.tree-chapter.is-open .arrow {
  transform: rotate(90deg);
}

.tree-chapter__name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chapter-count {
  font-size: 12px;
  font-weight: 400;
}

/* 「+ 页」：平时不出现，鼠标到这一章才亮 —— 大纲首先是用来读的 */
.tree-chapter__add {
  border: 1px dashed var(--td-component-stroke);
  background: transparent;
  border-radius: var(--td-radius-default);
  padding: 1px 6px;
  font-size: 11px;
  color: var(--td-text-secondary);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s;
}

.tree-chapter__title:hover .tree-chapter__add {
  opacity: 1;
}

.tree-chapter__add:hover {
  color: var(--td-brand-color);
  border-color: var(--td-brand-color);
}

.tree-page {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px 7px 30px;
  margin: 2px 0;
  font-size: 13px;
  color: var(--td-text-secondary);
  border-radius: var(--td-radius-default);
  cursor: pointer;
  transition: all 0.15s;
}

.tree-page:hover {
  background: var(--td-bg-container-hover);
}

.tree-page.is-selected {
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
  font-weight: 500;
}

.tree-page .p-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-page .p-status {
  margin-left: auto;
}

.tree-page .p-no {
  font-size: 11px;
  color: var(--td-text-placeholder);
}

/* 拖柄（原型 .tree-page .drag）：占着位置、鼠标到了才显形，行不会跳 */
.tree-page .drag {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
  color: var(--td-text-placeholder);
  opacity: 0;
  transition: opacity 0.15s;
}

.tree-page:hover .drag {
  opacity: 1;
}

.tree-page.is-dragging {
  opacity: 0.4;
}

/* 落点：一条上边线。插到目标页的前面还是后面由拖动方向决定（见 useOutlineDraft） */
.tree-page.is-over {
  box-shadow: inset 0 2px 0 0 var(--td-brand-color);
}

.tree-page__del {
  border: none;
  background: transparent;
  padding: 0 2px;
  font-size: 15px;
  line-height: 1;
  color: var(--td-text-placeholder);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s;
}

.tree-page:hover .tree-page__del {
  opacity: 1;
}

.tree-page__del:hover {
  color: var(--td-error-color);
}

.mono {
  font-family: var(--td-font-mono);
}
</style>
