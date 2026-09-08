<script setup lang="ts">
/** Markdown 渲染（主流 Agent 同款输出）：GFM + 代码块高亮 + 复制按钮。
 * DOMPurify 清洗防 XSS；复制按钮用事件委托，流式重渲染不受影响。
 * 流式性能：token 高频到达期间节流渲染（THROTTLE_MS 至多一次）且代码块跳过 hljs 全文高亮 ——
 * 逐 token 全量 marked+hljs+sanitize+DOMParser 会打满渲染主线程，表现为「卡住、工具执行完才整段出现」；
 * 流结束立即做一次完整渲染（补高亮、去光标）。 */
import { onUnmounted, ref, watch } from 'vue';
import DOMPurify from 'dompurify';
import { Marked } from 'marked';
import hljs from 'highlight.js/lib/common';
import 'highlight.js/styles/github-dark.css';

const props = defineProps<{ content: string; streaming?: boolean }>();

const marked = new Marked({ gfm: true, breaks: true });
// 代码块定制：语言标签 + 复制按钮头栏 + hljs 高亮（流式期间纯文本转义，结束后补高亮）
marked.use({
  renderer: {
    code({ text, lang }): string {
      const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext';
      const inner = props.streaming ? escapeHtml(text) : highlight(text, language);
      return [
        '<div class="code-block">',
        `<div class="code-head"><span class="code-lang">${escapeHtml(lang || 'text')}</span><button type="button" class="copy-btn">复制</button></div>`,
        `<pre><code class="hljs language-${language}">${inner}</code></pre>`,
        '</div>',
      ].join('');
    },
  },
});

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function highlight(text: string, language: string): string {
  try {
    return hljs.highlight(text, { language }).value;
  } catch {
    return escapeHtml(text);
  }
}

/** 流式节流窗口：至多每 100ms 渲染一次（≈10fps 足够阅读，主线程留出余量） */
const THROTTLE_MS = 100;
const html = ref('');
let timer: number | undefined;

function renderNow(): void {
  const clean = DOMPurify.sanitize(marked.parse(props.content ?? '') as string);
  html.value = props.streaming ? withStreamEdge(clean) : clean;
}

watch(
  [() => props.content, () => props.streaming],
  () => {
    if (!props.streaming) {
      if (timer !== undefined) {
        clearTimeout(timer);
        timer = undefined;
      }
      renderNow(); // 流结束：立即完整高亮 + 收掉光标
      return;
    }
    if (timer === undefined) {
      timer = window.setTimeout(() => {
        timer = undefined;
        renderNow();
      }, THROTTLE_MS);
    }
  },
  { immediate: true },
);
onUnmounted(() => {
  if (timer !== undefined) clearTimeout(timer);
});

/** Streaming Text 同款：末尾 TAIL_CHARS 个字符包 .stream-tail 软模糊消解，
 * 并在文末内联插入常亮细光标（操作已清洗 HTML 的最后一个文本节点，不会切断标签） */
const TAIL_CHARS = 6;
function withStreamEdge(clean: string): string {
  const doc = new DOMParser().parseFromString(`<div id="sb-root">${clean}</div>`, 'text/html');
  const root = doc.getElementById('sb-root');
  if (!root) return clean;
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let last: Text | null = null;
  let node: Node | null;
  while ((node = walker.nextNode())) if ((node.textContent ?? '').trim()) last = node as Text;
  const caret = doc.createElement('span');
  caret.className = 'stream-caret is-streaming';
  if (last?.textContent) {
    const tail = last.splitText(Math.max(0, last.textContent.length - TAIL_CHARS));
    const span = doc.createElement('span');
    span.className = 'stream-tail';
    tail.parentNode?.insertBefore(span, tail);
    span.appendChild(tail);
    span.after(caret);
  } else {
    root.appendChild(caret); // 首 token 未到：空内容也显示光标
  }
  return root.innerHTML;
}

/** 事件委托：点「复制」→ 取同块 pre 文本写剪贴板，短暂反馈「已复制」 */
function onContentClick(e: MouseEvent): void {
  const btn = (e.target as HTMLElement).closest('.copy-btn');
  if (!btn || !(btn instanceof HTMLButtonElement)) return;
  const pre = btn.closest('.code-block')?.querySelector('pre');
  void navigator.clipboard.writeText(pre?.textContent ?? '').then(() => {
    btn.textContent = '已复制 ✓';
    setTimeout(() => {
      btn.textContent = '复制';
    }, 1500);
  });
}
</script>

<template>
  <div class="md-body" @click="onContentClick" v-html="html" />
</template>
