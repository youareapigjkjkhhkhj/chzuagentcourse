<script setup lang="ts">
/**
 * 右栏工作台（P2 任务 1/7 / 原型 380px 三 Tab）：Diff / 代码 / 文件。
 * 状态集中在 useWorkbench（ChatView 持有），本组件只做布局与分发。
 * 宽度可拖拽：左缘手柄 mousemove 调整（右栏向左拖 = 变宽），localStorage 持久化。
 */
import { onUnmounted, ref } from 'vue';
import type { WorkbenchStore } from '../../composables/useWorkbench';
import { ico } from '../../ui/icons';
import CodeViewer from './CodeViewer.vue';
import DiffPanel from './DiffPanel.vue';
import FileTreePanel from './FileTreePanel.vue';
import PreviewPanel from './PreviewPanel.vue';

const props = defineProps<{ store: WorkbenchStore }>();

const TABS: Array<{ key: 'diff' | 'code' | 'files' | 'preview'; label: string }> = [
  { key: 'diff', label: 'Diff' },
  { key: 'code', label: '代码' },
  { key: 'files', label: '文件' },
  { key: 'preview', label: '预览' },
];

function onTab(key: 'diff' | 'code' | 'files' | 'preview'): void {
  if (key === 'files') void props.store.showFiles();
  else props.store.tab.value = key;
}

/** 拖拽宽度：默认 380（原型值），clamp 320–720 防拖没 / 拖爆 */
const WIDTH_KEY = 'agentbuddy.benchWidth';
const MIN_W = 320;
const MAX_W = 720;
function clampWidth(w: number): number {
  return Math.min(MAX_W, Math.max(MIN_W, Math.round(w)));
}
const width = ref(clampWidth(Number(localStorage.getItem(WIDTH_KEY)) || 380));

let dragStartX = 0;
let dragStartW = 0;
function startResize(e: MouseEvent): void {
  dragStartX = e.clientX;
  dragStartW = width.value;
  e.preventDefault(); // 拖拽期间禁止选中文本
  window.addEventListener('mousemove', onResizeMove);
  window.addEventListener('mouseup', endResize, { once: true });
}
function onResizeMove(e: MouseEvent): void {
  width.value = clampWidth(dragStartW + (dragStartX - e.clientX));
}
function endResize(): void {
  window.removeEventListener('mousemove', onResizeMove);
  localStorage.setItem(WIDTH_KEY, String(width.value));
}
onUnmounted(() => window.removeEventListener('mousemove', onResizeMove));
</script>

<template>
  <div class="relative border-l border-border bg-surface/60 flex flex-col shrink-0" :style="{ width: `${width}px` }">

    <!-- 拖拽手柄：左缘细条，hover 高亮提示可拉 -->
    <div
      class="absolute left-0 top-0 h-full w-1.5 -ml-1 cursor-col-resize hover:bg-accent/40 active:bg-accent/60 z-10"
      title="拖拽调整宽度"
      @mousedown="startResize"
    />

    <!-- 头部：Tab 切换 + 关闭 -->
    <div class="h-9 border-b border-border px-3 flex items-center justify-between shrink-0">
      <div class="flex items-center gap-1">
        <button
          v-for="t in TABS"
          :key="t.key"
          :class="[
            'px-2.5 py-1 rounded-md text-[11px] transition-std',
            store.tab.value === t.key
              ? 'bg-card text-stone-900 font-medium shadow-sm border border-border'
              : 'text-stone-500 hover:text-stone-700',
          ]"
          @click="onTab(t.key)"
        >{{ t.label }}</button>
      </div>
      <button class="text-stone-500 hover:text-stone-700 p-1 hover:bg-card rounded-md transition-std" v-html="ico('x')" @click="store.close()" />
    </div>

    <div class="flex-1 overflow-y-auto">
      <DiffPanel v-if="store.tab.value === 'diff'" :store="store" />

      <CodeViewer
        v-else-if="store.tab.value === 'code'"
        :path="store.codeFile.value"
        :content="store.codeContent.value"
        :error="store.codeError.value || undefined"
      />

      <PreviewPanel
        v-else-if="store.tab.value === 'preview' && store.previewFile.value"
        :path="store.previewFile.value"
        @view-source="() => void store.openCode(store.previewFile.value)"
      />
      <div v-else-if="store.tab.value === 'preview'" class="text-[11px] text-stone-400 py-8 text-center px-4">
        在「文件」树点击 html / md / 图片 / docx / pdf 即可预览
      </div>

      <div v-else class="p-2">
        <div v-if="store.tree.value.length === 0" class="text-[11px] text-stone-400 py-8 text-center">
          工作区为空或未选择
        </div>
        <FileTreePanel
          :nodes="store.tree.value"
          :active-path="store.codeFile.value"
          @open-file="(p) => void store.openFile(p)"
        />
      </div>
    </div>
  </div>
</template>
