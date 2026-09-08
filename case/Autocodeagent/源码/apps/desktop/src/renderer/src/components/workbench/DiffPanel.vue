<script setup lang="ts">
/**
 * Diff 审阅面板（P2 任务 2/3/4）：原型同款红绿行级渲染 + 双侧行号；
 * 头部一键接受全部文件（Qoder 同款）；接受/撤销后状态横幅（§原型）。
 */
import { computed } from 'vue';
import type { WorkbenchStore } from '../../composables/useWorkbench';
import { ico } from '../../ui/icons';

const props = defineProps<{ store: WorkbenchStore }>();

const current = computed(() =>
  props.store.changes.value.find((c) => c.changeId === props.store.selected.value) ?? null,
);

const KIND_LABEL: Record<string, string> = {
  modified: '修改',
  created: '新增',
  deleted: '删除',
  renamed: '重命名',
};

function lineClass(kind: string): string {
  if (kind === 'del') return 'diff-del';
  if (kind === 'add') return 'diff-add';
  return 'text-stone-500';
}
</script>

<template>
  <div class="p-3 space-y-3">

    <!-- 头部：一键接受全部（Qoder 同款） -->
    <div v-if="store.pendingCount.value > 0" class="flex items-center justify-between gap-2">
      <span class="text-[10.5px] text-stone-500">{{ store.pendingCount.value }} 个变更待审阅</span>
      <button
        class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-[11px] font-medium transition-std shadow-sm"
        @click="store.acceptAll()"
      >
        <span v-html="ico('check')" /> 一键接受全部文件
      </button>
    </div>

    <!-- 变更选择（多变更会话） -->
    <div v-if="store.changes.value.length > 1" class="flex flex-wrap gap-1.5">
      <button
        v-for="(c, i) in store.changes.value"
        :key="c.changeId"
        :class="[
          'px-2 py-1 rounded-md text-[10px] font-mono border transition-std',
          store.selected.value === c.changeId
            ? 'bg-card border-borderLight text-stone-800 shadow-sm'
            : 'border-border text-stone-500 hover:text-stone-700',
        ]"
        @click="store.select(c.changeId)"
      >
        #{{ store.changes.value.length - i }}
        <span v-if="c.status === 'pending'" class="text-amber-700">待审阅</span>
        <span v-else-if="c.status === 'accepted'" class="text-emerald-700">✓</span>
        <span v-else class="text-rose-600">↩</span>
      </button>
    </div>

    <div v-if="store.loadingDiff.value" class="text-[11px] text-stone-400 py-8 text-center">加载 Diff 中…</div>

    <template v-else-if="store.diffView.value">
      <!-- git 整树快照（bash 场景）：无逐文件明细 -->
      <div v-if="store.diffView.value.isGitSnapshot" class="bg-surface border border-border rounded-lg p-3 text-[11px] text-stone-600 space-y-1">
        <div class="flex items-center gap-1.5 text-stone-700 font-medium"><span v-html="ico('terminal')" /> 命令执行的整树快照</div>
        <div class="text-stone-500">无逐文件明细（git 仓库快照），撤销将把整个工作区还原到执行前。</div>
      </div>

      <!-- 逐文件 Diff -->
      <div v-for="f in store.diffView.value.files" :key="f.path" class="space-y-1.5">
        <div class="flex items-center justify-between">
          <span class="font-mono text-[11px] text-stone-700 flex items-center gap-1.5 min-w-0">
            <span class="text-stone-400 shrink-0" v-html="ico('file')" />
            <span class="truncate">{{ f.path }}</span>
            <span class="text-[9px] px-1.5 py-0.5 rounded-full bg-stone-500/10 text-stone-500 shrink-0">{{ KIND_LABEL[f.kind] ?? f.kind }}</span>
          </span>
          <span class="font-mono text-[10px] shrink-0">
            <span class="text-emerald-700">+{{ f.insertions }}</span>
            <span class="text-rose-600 ml-1">-{{ f.deletions }}</span>
          </span>
        </div>

        <div class="bg-[#fbfaf7] border border-border rounded-lg overflow-hidden overflow-x-auto font-mono text-[11px] leading-5 shadow-card">
          <div v-for="(line, i) in f.lines" :key="i" :class="['px-2 flex', lineClass(line.kind)]">
            <span class="w-7 text-right pr-1 text-stone-400/80 shrink-0 select-none">{{ line.oldNo ?? '' }}</span>
            <span class="w-7 text-right pr-2 text-stone-400/80 shrink-0 select-none border-r border-border/60">{{ line.newNo ?? '' }}</span>
            <span class="pl-2 whitespace-pre">{{ line.text }}</span>
          </div>
          <div v-if="f.lines.length === 0" class="px-3 py-2 text-[10.5px] text-stone-400">（内容无变化）</div>
        </div>
      </div>

      <!-- 操作区 / 状态横幅（原型同款） -->
      <div v-if="store.diffView.value.status === 'pending'" class="flex gap-2">
        <button
          class="flex-1 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-[11px] font-medium transition-std"
          @click="current && store.accept(current.changeId)"
        >接受修改</button>
        <button
          class="flex-1 py-1.5 bg-border hover:bg-borderLight text-stone-700 rounded-lg text-[11px] transition-std"
          @click="current && store.revert(current.changeId)"
        >撤销</button>
      </div>
      <div
        v-else-if="store.diffView.value.status === 'accepted'"
        class="bg-emerald-500/10 border border-emerald-500/25 text-emerald-700 rounded-lg px-3 py-2 text-[11px] flex items-center gap-1.5"
      >
        <span v-html="ico('check')" /> 修改已接受并写入工作区
      </div>
      <div v-else class="bg-rose-500/10 border border-rose-500/25 text-rose-600 rounded-lg px-3 py-2 text-[11px]">↩ 修改已撤销，文件未变更</div>
    </template>

    <div v-else-if="!store.actionError.value" class="text-[11px] text-stone-400 py-8 text-center">
      暂无变更：Agent 修改文件后会在这里审阅
    </div>

    <div v-if="store.actionError.value" class="bg-rose-50 border border-rose-500/30 rounded-lg px-3 py-2 text-[11px] text-rose-600">
      {{ store.actionError.value }}
    </div>
  </div>
</template>
