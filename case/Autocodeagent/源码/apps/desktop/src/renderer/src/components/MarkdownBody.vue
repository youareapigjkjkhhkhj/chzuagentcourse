<script setup lang="ts">
/** Markdown 渲染（主流 Agent 同款输出）：GFM + 代码块高亮 + 复制按钮。
 * DOMPurify 清洗防 XSS；复制按钮用事件委托，流式重渲染不受影响。
 * 流式性能（跟随模型吐字原速、平滑不卡顿）：requestAnimationFrame 合帧渲染替代旧的固定 100ms 节流——
 * 一帧内到达的多个 token 只跑一次 marked+sanitize，既跟手（≈60fps）又每帧至多一次，不打满主线程；
 * 流式期间代码块跳过 hljs 全文高亮，末尾光标改由纯 CSS（.md-body.is-streaming）绘制，
 * 不再每帧 DOMParser 重解析整段 HTML（旧实现 O(n)/帧、长回复累积 O(n²) 卡顿）。流结束立即完整高亮渲染。 */
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

const html = ref('');
let raf: number | undefined;

function renderNow(): void {
  html.value = DOMPurify.sanitize(marked.parse(props.content ?? '') as string);
}

/** 流式按帧合并：一帧内多次 token 只渲染一次，跟随模型原速且每帧至多一次，不打满主线程 */
function scheduleRender(): void {
  if (raf !== undefined) return;
  raf = requestAnimationFrame(() => {
    raf = undefined;
    renderNow();
  });
}

watch(
  [() => props.content, () => props.streaming],
  () => {
    if (!props.streaming) {
      if (raf !== undefined) {
        cancelAnimationFrame(raf);
        raf = undefined;
      }
      renderNow(); // 流结束：立即完整高亮（末尾光标随 is-streaming class 移除而消失）
      return;
    }
    // 首帧立即出字，避免气泡挂载瞬间空白闪一下；其后按帧合并渲染
    if (html.value === '') renderNow();
    else scheduleRender();
  },
  { immediate: true },
);
onUnmounted(() => {
  if (raf !== undefined) cancelAnimationFrame(raf);
});

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
  <div class="md-body" :class="{ 'is-streaming': streaming }" @click="onContentClick" v-html="html" />
</template>
