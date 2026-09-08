<script setup lang="ts">
/**
 * 右栏预览面板：按格式渲染工作区产出文件（html / markdown / 图片 / docx / pdf）。
 * 内容经 workspace.preview 的 base64 通道读取；docx / pdf 渲染库动态 import 做代码分割。
 */
import { computed, nextTick, onUnmounted, ref, watch } from 'vue';
import { agent } from '../../api/bridge';
import { ico } from '../../ui/icons';
import { previewKind, type PreviewKind } from '../../ui/previewKind';
import MarkdownBody from '../MarkdownBody.vue';

const props = defineProps<{ path: string }>();
const emit = defineEmits<{ (e: 'view-source'): void }>();

const kind = ref<PreviewKind | null>(null);
const loading = ref(false);
const error = ref('');
/** html / markdown 解码文本 */
const text = ref('');
/** 图片 objectURL */
const objectUrl = ref('');
/** docx / pdf 渲染容器 */
const docHost = ref<HTMLElement | null>(null);
const pdfHost = ref<HTMLElement | null>(null);

const fileName = computed(() => props.path.split(/[\\/]/).filter(Boolean).pop() ?? props.path);

/** HTML 预览 URL：abp://ws/<逐段编码的工作区相对路径>。保留目录层级，页面内相对
 * css/js/图片才能按真实结构解析（main 侧经 workspace jail 只读服务，见 main/index.ts）。 */
const htmlSrc = computed(() => `abp://ws/${props.path.split(/[\\/]/).map(encodeURIComponent).join('/')}`);

let currentUrl = '';
function revoke(): void {
  if (currentUrl) URL.revokeObjectURL(currentUrl);
  currentUrl = '';
  objectUrl.value = '';
}

function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

async function renderDocx(bytes: Uint8Array): Promise<void> {
  const el = docHost.value;
  if (!el) return;
  el.textContent = '';
  const { renderAsync } = await import('docx-preview');
  await renderAsync(bytes, el);
}

async function renderPdf(bytes: Uint8Array): Promise<void> {
  const el = pdfHost.value;
  if (!el) return;
  el.textContent = '';
  const pdfjs = await import('pdfjs-dist');
  pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString();
  const doc = await pdfjs.getDocument({ data: bytes.slice() }).promise;
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const viewport = page.getViewport({ scale: 1.4 });
    const canvas = document.createElement('canvas');
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    el.appendChild(canvas);
    const ctx = canvas.getContext('2d');
    if (!ctx) continue;
    await page.render({ canvasContext: ctx, viewport }).promise;
  }
}

async function load(): Promise<void> {
  revoke();
  text.value = '';
  error.value = '';
  kind.value = previewKind(props.path);
  if (kind.value === null) {
    error.value = '该格式暂不支持预览';
    return;
  }
  // HTML：交给 abp:// 协议 iframe 直接加载（保留目录结构 → 相对资源可解析），不走 base64 通道
  if (kind.value === 'html') {
    loading.value = false;
    return;
  }
  loading.value = true;
  const res = await agent().workspace.preview(props.path);
  if (!res.ok || !res.data) {
    loading.value = false;
    error.value = res.error ?? '读取文件失败';
    return;
  }
  const bytes = base64ToBytes(res.data.base64);
  const k = kind.value;
  if (k === 'markdown') {
    text.value = new TextDecoder('utf-8').decode(bytes);
    loading.value = false;
  } else if (k === 'image') {
    currentUrl = URL.createObjectURL(new Blob([bytes], { type: res.data.mime }));
    objectUrl.value = currentUrl;
    loading.value = false;
  } else {
    // docx / pdf：容器须先挂载（kind 已置位），nextTick 后渲染进 ref
    await nextTick();
    try {
      if (k === 'docx') await renderDocx(bytes);
      else await renderPdf(bytes);
    } catch (e) {
      error.value = `渲染失败：${(e as Error).message}`;
    } finally {
      loading.value = false;
    }
  }
}

watch(() => props.path, () => void load(), { immediate: true });
onUnmounted(revoke);
</script>

<template>
  <div class="flex flex-col h-full min-h-0">
    <!-- 头部：文件名 + 查看源码 -->
    <div class="h-8 px-3 border-b border-border flex items-center justify-between shrink-0 bg-surface/40">
      <span class="font-mono text-[11px] text-stone-700 truncate" :title="path">{{ fileName }}</span>
      <button
        class="text-[10px] text-stone-500 hover:text-stone-700 flex items-center gap-1 shrink-0 transition-std"
        title="在代码 Tab 查看源码"
        @click="emit('view-source')"
      >
        <span v-html="ico('file')" /> 源码
      </button>
    </div>

    <div class="relative flex-1 min-h-0 overflow-auto bg-white">
      <div v-if="error" class="text-[11px] text-rose-500 py-10 text-center px-4 bg-surface/40">{{ error }}</div>
      <template v-else-if="kind">
        <iframe v-if="kind === 'html'" :src="htmlSrc" sandbox="allow-scripts" class="w-full h-full border-0 bg-white" title="preview" />
        <div v-else-if="kind === 'markdown'" class="p-4 text-stone-800">
          <MarkdownBody :content="text" :streaming="false" />
        </div>
        <div v-else-if="kind === 'image'" class="p-4 flex items-center justify-center bg-stone-100">
          <img :src="objectUrl" class="max-w-full h-auto shadow" :alt="fileName" />
        </div>
        <div v-else-if="kind === 'docx'" ref="docHost" class="docx-host p-4" />
        <div v-else-if="kind === 'pdf'" ref="pdfHost" class="pdf-host p-4 space-y-3" />
      </template>
      <div v-if="loading" class="absolute inset-0 bg-white/70 flex items-center justify-center text-[11px] text-stone-400">加载预览…</div>
    </div>
  </div>
</template>

<style>
/* 运行时注入的 canvas / docx 节点无 scoped 属性，用类名命名空间全局约束 */
.pdf-host canvas { display: block; margin: 0 auto; max-width: 100%; height: auto; box-shadow: 0 1px 4px rgb(0 0 0 / 0.25); }
.docx-host .docx-wrapper { background: transparent; padding: 8px 0; }
.docx-host .docx-wrapper > section.docx { margin: 0 auto 12px; box-shadow: 0 1px 4px rgb(0 0 0 / 0.2); }
</style>
