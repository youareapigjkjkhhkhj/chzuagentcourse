<script setup lang="ts">
/** 代码只读查看（P2 任务 7）：行号 + highlight.js 语法着色（按扩展名） */
import { computed } from 'vue';
import hljs from 'highlight.js/lib/common';
import 'highlight.js/styles/github.css';
import { ico } from '../../ui/icons';

const props = defineProps<{ path: string; content: string; error?: string }>();

/** 扩展名 → hljs 语言（common 子集，未命中退回 plaintext） */
const LANG_OF: Record<string, string> = {
  ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript', mjs: 'javascript',
  json: 'json', md: 'markdown', py: 'python', yaml: 'yaml', yml: 'yaml',
  html: 'xml', vue: 'xml', css: 'css', scss: 'scss', sh: 'bash', bash: 'bash',
  sql: 'sql', java: 'java', go: 'go', rs: 'rust', toml: 'ini', ini: 'ini', xml: 'xml',
};

const highlighted = computed(() => {
  const ext = props.path.split('.').pop()?.toLowerCase() ?? '';
  const lang = LANG_OF[ext] && hljs.getLanguage(LANG_OF[ext] ?? '') ? (LANG_OF[ext] ?? 'plaintext') : 'plaintext';
  try {
    return hljs.highlight(props.content, { language: lang }).value;
  } catch {
    return escapeHtml(props.content);
  }
});

/** 高亮后按行拆分：行尾闭合未关闭的 span，行首重开（跨行片段保持着色） */
const lines = computed(() => splitHighlightedLines(highlighted.value));

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function splitHighlightedLines(html: string): string[] {
  const result: string[] = [];
  let stack: string[] = [];
  for (const raw of html.split('\n')) {
    const prefix = stack.join(''); // 行首重开上一行未闭合的标签（保持跨行着色）
    for (const m of raw.matchAll(/<span[^>]*>|<\/span>/g)) {
      if (m[0] === '</span>') stack.pop();
      else stack.push(m[0]);
    }
    result.push(prefix + raw + '</span>'.repeat(stack.length)); // 行尾闭合本行打开的标签
  }
  return result;
}
</script>

<template>
  <div class="bg-[#fbfaf7] font-mono text-[11px] leading-5 min-h-full">
    <div class="text-stone-500 mb-2 flex items-center gap-1.5 px-3 pt-2">
      <span v-html="ico('file')" /> {{ path }}
      <span v-if="error" class="text-rose-600 ml-2">{{ error }}</span>
    </div>
    <div v-if="!error" class="hljs-reset pb-2">
      <div v-for="(line, i) in lines" :key="i" class="px-2 flex">
        <span class="w-7 text-right pr-2 text-stone-400 shrink-0 select-none">{{ i + 1 }}</span>
        <span class="whitespace-pre text-stone-700" v-html="line" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* hljs github 主题作用于行内片段，背景保持面板奶白 */
.hljs-reset :deep(.hljs) { background: transparent; padding: 0; }
</style>
