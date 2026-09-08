<script setup lang="ts">
/** 文件树（P2 任务 7）：递归渲染工作区目录，点击文件 → 代码只读查看 */
import { ref } from 'vue';
import type { TreeNode } from '@agentbuddy/shared';
import { ico } from '../../ui/icons';

defineProps<{ nodes: TreeNode[]; depth?: number; activePath?: string }>();
const emit = defineEmits<{ (e: 'open-file', path: string): void }>();

const expanded = ref<Set<string>>(new Set());

function toggle(node: TreeNode): void {
  if (expanded.value.has(node.path)) expanded.value.delete(node.path);
  else expanded.value.add(node.path);
}
</script>

<template>
  <div class="font-mono text-[11px] text-stone-600">
    <template v-for="n in nodes" :key="n.path">
      <div
        :class="[
          'px-2 py-1 rounded-md flex items-center gap-1.5 cursor-pointer hover:bg-card transition-std',
          activePath === n.path && 'bg-accent/10 text-accent',
        ]"
        :style="{ paddingLeft: ((depth ?? 0) * 14 + 8) + 'px' }"
        @click="n.dir ? toggle(n) : emit('open-file', n.path)"
      >
        <span v-if="n.dir" class="text-[9px] text-stone-400 w-2.5 inline-block transition-transform" :class="expanded.has(n.path) ? 'rotate-90' : ''">▶</span>
        <span v-else class="w-2.5 inline-block" />
        <span :class="n.dir ? 'text-amber-700/70' : 'text-stone-400'" v-html="ico(n.dir ? 'folder' : 'file')" />
        <span class="truncate">{{ n.name }}</span>
      </div>
      <FileTreePanel
        v-if="n.dir && n.children && expanded.has(n.path)"
        :nodes="n.children"
        :depth="(depth ?? 0) + 1"
        :active-path="activePath"
        @open-file="(p) => emit('open-file', p)"
      />
    </template>
  </div>
</template>
