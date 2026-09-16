<script setup lang="ts">
/** Tool Trace 行（参考 beautifului.dev Tool Chips 设计语言）：
 * 无边框紧凑行 = 工具图标 + 名称 + 内嵌摘要 chip + 状态；hover 图标变箭头；
 * 点击展开「左竖线」详情（格式化入参 + 输出）；失败自动展开。
 * 带变更集时行尾挂 Diff 小 chip（一键打开右栏审阅）。入参不裸显 JSON。 */
import { computed, ref, watch } from 'vue';
import type { ChatMessage, ReviewStatus } from '@agentbuddy/shared';
import { ico } from '../ui/icons';

const props = defineProps<{ msg: ChatMessage; reviewStatus?: ReviewStatus | null }>();
const emit = defineEmits<{ (e: 'view-diff', changeId: string): void }>();

const TOOL_ICON: Record<string, string> = {
  read: 'file',
  glob: 'search',
  grep: 'search',
  write: 'pencil',
  edit: 'pencil',
  bash: 'terminal',
  todo_write: 'check',
  use_skill: 'sparkle',
  task: 'bot',
  webfetch: 'globe',
  websearch: 'globe',
};

const RISK_CLASS: Record<string, string> = {
  WRITE: 'text-amber-700 bg-amber-500/10',
  EXEC: 'text-blue-700 bg-blue-500/10',
  NETWORK: 'text-purple-700 bg-purple-500/10',
  DANGEROUS: 'text-rose-700 bg-rose-500/10',
};

/** 默认折叠；执行失败自动展开（错误信息直接可见） */
const expanded = ref(props.msg.toolOk === false);
watch(() => props.msg.toolOk, (ok) => { if (ok === false) expanded.value = true; });

/** P5：MCP 工具展示名映射 mcp__{server}__{tool} → {server} / {tool}（验收：github / create_issue 形式）；
 * 技能自取工具直接展示技能名（技能 /review），一眼看出调了哪个技能 */
const displayName = computed(() => {
  const name = props.msg.toolName ?? '';
  if (name === 'use_skill') {
    const raw = argsObj.value['name'];
    const skill = typeof raw === 'string' ? raw.replace(/^\//, '').trim() : '';
    return skill ? `技能 /${skill}` : '调用技能';
  }
  const m = /^mcp__([^_].*?)__(.+)$/.exec(name);
  return m ? `${m[1]} / ${m[2]}` : name;
});

function iconOf(name?: string): string {
  if (name?.startsWith('mcp__')) return ico('plug');
  return ico(TOOL_ICON[name ?? ''] ?? 'gear');
}

function riskOf(msg: ChatMessage): string {
  const n = msg.toolName ?? '';
  if (n.startsWith('mcp__')) return 'NETWORK';
  if (n === 'webfetch' || n === 'websearch') return 'NETWORK';
  if (n === 'bash') return 'EXEC';
  if (n === 'write' || n === 'edit') return 'WRITE';
  return 'READ';
}

/** 安全解析入参（解析失败回退空对象，绝不向用户裸抛 JSON 原文） */
const argsObj = computed<Record<string, unknown>>(() => {
  if (!props.msg.toolArgs) return {};
  try {
    const v: unknown = JSON.parse(props.msg.toolArgs);
    return v && typeof v === 'object' ? v as Record<string, unknown> : {};
  } catch {
    return {};
  }
});

const sOf = (k: string): string => (typeof argsObj.value[k] === 'string' ? argsObj.value[k] as string : '');

/** 行内人读摘要 chip：read → 路径（+起行）；edit/write → 路径；grep/glob → 模式；bash → 命令截断 */
const summary = computed<string>(() => {
  const a = argsObj.value;
  const path = sOf('path');
  switch (props.msg.toolName) {
    case 'read': {
      const off = typeof a['offset'] === 'number' ? ` · 从第 ${a['offset']} 行` : '';
      return path ? `${path}${off}` : '';
    }
    case 'write':
    case 'edit':
      return path;
    case 'glob':
      return sOf('pattern') || path;
    case 'grep':
      return sOf('pattern');
    case 'bash': {
      const c = sOf('command').replace(/\s+/g, ' ');
      return c.length > 48 ? `${c.slice(0, 48)}…` : c;
    }
    case 'todo_write': {
      const todos = argsObj.value['todos'];
      return Array.isArray(todos) ? `${todos.length} 项` : '';
    }
    case 'use_skill':
      // 技能名已并入主标签（技能 /review），此处不再重复 chip
      return '';
    case 'webfetch':
      return sOf('url');
    case 'websearch':
      return sOf('query');
    case 'task': {
      // 执行中显示子代理实时进度（子代理 · edit 手册3.md）；完成 / 未开始回退子任务 prompt 截断
      const prog = props.msg.toolProgress;
      if (props.msg.toolOk === undefined && prog) return `子代理 · ${prog}`;
      const pr = sOf('prompt');
      return pr ? (pr.length > 40 ? `${pr.slice(0, 40)}…` : pr) : '子代理';
    }
    default:
      // MCP 工具：无固定入参约定，退化为首个字符串参数摘要（截断）
      if ((props.msg.toolName ?? '').startsWith('mcp__')) {
        const first = Object.values(argsObj.value).find((v) => typeof v === 'string') as string | undefined;
        if (!first) return '';
        return first.length > 48 ? `${first.slice(0, 48)}…` : first;
      }
      return path || sOf('pattern') || '';
  }
});

interface ArgRow { key: string; value: string; long: boolean }

/** 展开区格式化入参：短值行内键值对，长值/多行值独立分块（上限 600 字截断） */
const argRows = computed<ArgRow[]>(() => {
  const out: ArgRow[] = [];
  for (const [k, v] of Object.entries(argsObj.value)) {
    let value = typeof v === 'string' ? v : JSON.stringify(v);
    if (value.length > 600) value = `${value.slice(0, 600)}\n…（已截断）`;
    out.push({ key: k, value, long: value.length > 72 || value.includes('\n') });
  }
  return out;
});

/** 审阅状态文案（原型：待审阅 / ✓ 已接受 / ↩ 已撤销） */
function reviewLabel(s: ReviewStatus | null | undefined): string {
  if (s === 'accepted') return '✓ 已接受';
  if (s === 'reverted') return '↩ 已撤销';
  return '待审阅';
}

function reviewClass(s: ReviewStatus | null | undefined): string {
  if (s === 'accepted') return 'text-emerald-700';
  if (s === 'reverted') return 'text-rose-600';
  return 'text-amber-700';
}
</script>

<template>
  <div class="group/row min-w-0">
    <!-- 折叠行：图标(hover 变箭头) + 名称 + 摘要 chip + 风险 + 耗时 + 状态 + Diff chip -->
    <button
      class="-mx-1.5 flex h-7 w-fit max-w-full items-center gap-2 rounded-lg px-1.5 text-left hover:bg-stone-500/5 transition-std"
      :title="expanded ? '收起' : '展开详情'"
      @click="expanded = !expanded"
    >
      <span class="relative flex w-3.5 shrink-0 items-center justify-center text-stone-500">
        <span class="transition-std" :class="expanded ? 'opacity-0' : 'group-hover/row:opacity-0'" v-html="iconOf(msg.toolName)" />
        <span
          class="absolute transition-std"
          :class="expanded ? 'opacity-100 rotate-0' : 'opacity-0 -rotate-90 group-hover/row:opacity-100'"
          v-html="ico('chevron')"
        />
      </span>
      <span class="shrink-0 text-[12px] font-medium text-stone-800">{{ displayName }}</span>
      <span
        v-if="summary"
        class="inline-block max-w-[320px] truncate rounded-md bg-surface px-1.5 text-[11px] leading-[22px] font-mono text-stone-600 shadow-card"
      >{{ summary }}</span>
      <span v-if="riskOf(msg) !== 'READ'" :class="['px-1.5 py-0.5 rounded-full text-[9.5px] font-medium shrink-0', RISK_CLASS[riskOf(msg)]]">{{ riskOf(msg) }}</span>
      <span v-if="msg.toolMs !== undefined" class="text-[10px] text-stone-500 font-mono tabular-nums shrink-0">{{ msg.toolMs }}ms</span>
      <span class="flex items-center gap-1.5 shrink-0">
        <span v-if="msg.toolChangeId && msg.toolOk" :class="['text-[10px]', reviewClass(reviewStatus)]">{{ reviewLabel(reviewStatus) }}</span>
        <span v-if="msg.toolOk === undefined" class="text-stone-500 flex items-center gap-1 text-[10px]">
          <span class="caret" /> 执行中
        </span>
        <span v-else-if="msg.toolOk" class="text-emerald-700" v-html="ico('check')" />
        <span v-else class="text-rose-600" v-html="ico('x')" />
      </span>
      <!-- Diff 小 chip（Tool Chips 文件 chip 同款）：一键打开右栏审阅 -->
      <span
        v-if="msg.toolChangeId && msg.toolOk"
        class="inline-flex h-6 items-center gap-1 rounded-md bg-card px-2 font-mono text-[10.5px] text-stone-600 shadow-card hover:bg-cardHover transition-std"
        @click.stop="msg.toolChangeId && emit('view-diff', msg.toolChangeId)"
      >
        <span v-html="ico('diff')" /> 查看 Diff
      </span>
    </button>

    <!-- 展开区：左竖线详情（Tool Chips 同款） -->
    <div
      class="grid transition-all duration-300"
      :style="{ gridTemplateRows: expanded ? '1fr' : '0fr', opacity: expanded ? 1 : 0 }"
    >
      <div class="min-h-0 overflow-hidden">
        <div class="mt-0.5 mb-1.5 ml-2 border-l border-border py-1 pl-3.5 space-y-1 text-[10.5px] font-mono">
          <template v-for="r in argRows" :key="r.key">
            <div v-if="!r.long" class="flex gap-1.5 min-w-0">
              <span class="text-stone-500 shrink-0">{{ r.key }}</span>
              <span class="text-stone-700 truncate">{{ r.value }}</span>
            </div>
            <div v-else>
              <span class="text-stone-500">{{ r.key }}</span>
              <pre class="mt-0.5 bg-stone-500/5 border border-border/60 rounded-md px-2 py-1 max-h-32 overflow-y-auto text-[10.5px] leading-relaxed text-stone-700 whitespace-pre-wrap break-all select-text">{{ r.value }}</pre>
            </div>
          </template>
          <pre v-if="msg.content && (msg.toolName !== 'use_skill' || msg.toolOk === false)" class="max-h-44 overflow-y-auto text-[11px] leading-relaxed text-stone-800 whitespace-pre-wrap select-text">{{ msg.content }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
