<script setup lang="ts">
/**
 * 内联权限确认卡（P2 任务 6 / 原型琥珀色卡）：
 * 拒绝 / 允许一次 / 始终允许（本会话）；DANGEROUS 不提供始终允许（§4.2）。
 */
import type { PendingPermission } from '../composables/useAgent';
import { ico } from '../ui/icons';

defineProps<{ pending: PendingPermission }>();
const emit = defineEmits<{ (e: 'resolve', allow: boolean, remember: boolean): void }>();

const RISK_HINT: Record<string, string> = {
  WRITE: '将修改工作区文件',
  EXEC: '将在工作区执行命令',
  NETWORK: '将发起网络请求',
  DANGEROUS: '高风险操作，可能造成不可逆影响',
};
</script>

<template>
  <div class="bg-amber-50 border border-amber-500/30 rounded-lg p-3 space-y-2 text-xs shadow-card">
    <div class="flex items-center justify-between text-amber-700 font-medium">
      <span class="flex items-center gap-1.5">
        <span v-html="ico('alert')" />
        需要确认：{{ RISK_HINT[pending.risk] ?? '该操作需要你确认' }}
      </span>
      <span class="text-[9px] bg-amber-500/15 px-1.5 py-0.5 rounded-full font-mono">{{ pending.risk }}</span>
    </div>

    <div class="bg-[#f7f5ef] p-2 rounded-md font-mono text-[11px] text-stone-700 border border-amber-500/15 whitespace-pre-wrap break-all max-h-32 overflow-y-auto select-text">
      <span class="text-stone-400">{{ pending.name }} · </span>{{ pending.detail }}
    </div>

    <div class="flex justify-end gap-2 pt-1">
      <button class="px-2.5 py-1 bg-border hover:bg-borderLight text-stone-700 rounded-md transition-std" @click="emit('resolve', false, false)">拒绝</button>
      <button class="px-3 py-1 bg-amber-600 hover:bg-amber-500 text-white rounded-md font-medium transition-std" @click="emit('resolve', true, false)">允许一次</button>
      <button
        v-if="pending.risk !== 'DANGEROUS'"
        class="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-md font-medium transition-std"
        @click="emit('resolve', true, true)"
      >始终允许（本会话）</button>
    </div>
  </div>
</template>
