<script setup lang="ts">
/** 大输入卡片 —— 与原型场景 A/B 底部输入区 1:1 同款 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import type { ChatImage, PermissionMode, SkillMeta, WorkspaceEntry } from '@agentbuddy/shared';
import { ico } from '../ui/icons';
import { modeMeta, PERM_OPTIONS } from '../ui/permModes';
import { formatTokens, levelToContextWindow, levelToMaxTokens, POWER_MAX } from '../ui/modelPower';

const props = defineProps<{
  modelValue: string;
  busy: boolean;
  disabled: boolean;
  workspaceName: string;
  /** 多工作区：历史关联目录清单（下拉切换）+ 当前活动目录 */
  roots: string[];
  activeRoot: string | null;
  /** 已配置的模型列表（模型配置中心） */
  models: Array<{ id: string; name: string }>;
  /** 当前使用的模型 id */
  modelId: string;
  /** 火力档位（0..POWER_MAX）：联动 contextWindow/maxTokens，拖到最大 = 尽量用满模型能力 */
  power: number;
  /** P3：工作区默认权限（盾牌三档，持久化 config.json） */
  permMode: PermissionMode;
  /** P4：启用技能清单（/ 弹出菜单） */
  skills: SkillMeta[];
  /** P5：MCP 连接器清单（# 弹出菜单；未连接置灰不可选） */
  servers: Array<{ name: string; description: string; connected: boolean; icon?: string }>;
  /** 工作区条目清单（@ 弹出菜单：文件夹 + 文件，同主流 Agent 产品） */
  files: WorkspaceEntry[];
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void;
  (e: 'send', images: ChatImage[]): void;
  (e: 'stop'): void;
  (e: 'pick-workspace'): void;
  /** 多工作区：切换到某个历史目录 / 移除某个关联目录 */
  (e: 'select-root', path: string): void;
  (e: 'remove-root', path: string): void;
  (e: 'select-model', id: string): void;
  (e: 'set-power', level: number): void;
  (e: 'select-mode', mode: PermissionMode): void;
}>();

// P0 仅 UI 状态：Agent 工具执行自 P1 接入；Ask = 副作用均确认（安全默认）
const chatMode = ref<'chat' | 'agent'>('agent');
const showPermMenu = ref(false);

/** 火力档位滑块：本地态实时跟手（v-model 随 @input 更新标签），松手（@change）才 emit 持久化，
 * 避免拖动过程频繁写盘；父级 power 变化（切模型 / 写回成功）时同步本地态。 */
const localPower = ref(props.power);
watch(() => props.power, (v) => { localPower.value = v; });
const powerWindowLabel = computed(() => formatTokens(levelToContextWindow(localPower.value)));
const powerOutputLabel = computed(() => formatTokens(levelToMaxTokens(localPower.value)));
const powerMaxed = computed(() => localPower.value >= POWER_MAX);

/** 工作区下拉切换器：选历史工作区（roots）/ 新建（原生文件夹对话框）/ 移除关联目录 */
const showWsMenu = ref(false);
const wsMenuRef = ref<HTMLElement | null>(null);
function nameOf(p: string): string {
  return p.split(/[\\/]/).filter(Boolean).pop() ?? p;
}
function pickRoot(path: string): void {
  showWsMenu.value = false;
  if (path !== props.activeRoot) emit('select-root', path);
}
function removeRoot(path: string): void {
  emit('remove-root', path);
  if (props.roots.length <= 1) showWsMenu.value = false; // 移除最后一个后收起（回到空态）
}
function newWorkspace(): void {
  showWsMenu.value = false;
  emit('pick-workspace');
}
/** 点击菜单外部关闭（下拉选择器标准交互） */
function onDocDown(e: MouseEvent): void {
  if (showWsMenu.value && wsMenuRef.value && !wsMenuRef.value.contains(e.target as Node)) showWsMenu.value = false;
}
onMounted(() => document.addEventListener('mousedown', onDocDown));
onUnmounted(() => document.removeEventListener('mousedown', onDocDown));

/** P4：/ 技能菜单——键入 /名字 前缀时弹出；↑↓ 选择、回车确认、Esc 关闭，点击补全为 /name */
const skillQuery = computed(() => {
  const m = /^\/([\w-]*)$/.exec(props.modelValue);
  return m ? (m[1] ?? '') : null;
});
const menuDismissed = ref(false);
const activeIdx = ref(0);
watch(skillQuery, () => {
  menuDismissed.value = false;
  activeIdx.value = 0;
});
const skillMenu = computed(() => {
  if (skillQuery.value === null || menuDismissed.value) return [];
  const q = skillQuery.value.toLowerCase();
  return props.skills.filter((s) => s.name.toLowerCase().startsWith(q)).slice(0, 8);
});
watch(skillMenu, (m) => {
  if (activeIdx.value >= m.length) activeIdx.value = 0;
});
function pickSkill(name: string): void {
  emit('update:modelValue', `/${name} `);
}

/** P5：# MCP 连接器菜单——键入 #名字 前缀时弹出；已连接在前，未连接置灰不可选 */
const mcpQuery = computed(() => {
  const m = /(^|\s)#([\w-]*)$/.exec(props.modelValue);
  return m ? (m[2] ?? '') : null;
});
const mcpMenu = computed(() => {
  if (mcpQuery.value === null || menuDismissed.value || skillMenu.value.length > 0) return [];
  const q = mcpQuery.value.toLowerCase();
  const matched = props.servers.filter((s) => s.name.toLowerCase().startsWith(q)).slice(0, 8);
  return [...matched.filter((s) => s.connected), ...matched.filter((s) => !s.connected)];
});
watch(mcpQuery, () => {
  menuDismissed.value = false;
  activeIdx.value = 0;
});
watch(mcpMenu, (m) => {
  if (activeIdx.value >= m.length) activeIdx.value = 0;
});
function pickMcp(name: string): void {
  emit('update:modelValue', props.modelValue.replace(/#[\w-]*$/, `#${name} `));
}

/** 工作区条目菜单——键入 @路径 时弹出；支持中文路径（不能用 \w，仅 ASCII）；按相关度排序 */
const fileQuery = computed(() => {
  const m = /(^|\s)@([^\s]*)$/.exec(props.modelValue);
  return m ? (m[2] ?? '') : null;
});
const fileMenu = computed(() => {
  if (fileQuery.value === null || menuDismissed.value || skillMenu.value.length > 0 || mcpMenu.value.length > 0) return [];
  const q = fileQuery.value.toLowerCase();
  // 相关度：文件名前缀 > 文件名子串 > 全路径子串；同分保持树序（文件夹在前）
  return props.files
    .flatMap((f) => {
      const name = f.path.split('/').pop()!.toLowerCase();
      const score = name.startsWith(q) ? 0 : name.includes(q) ? 1 : f.path.toLowerCase().includes(q) ? 2 : -1;
      return score >= 0 ? [{ f, score }] : [];
    })
    .sort((a, b) => a.score - b.score)
    .slice(0, 12)
    .map((x) => x.f);
});
watch(fileQuery, () => {
  menuDismissed.value = false;
  activeIdx.value = 0;
});
watch(fileMenu, (m) => {
  if (activeIdx.value >= m.length) activeIdx.value = 0;
});
function pickFile(entry: WorkspaceEntry): void {
  // 文件夹：插入 @dir/ 后继续收窄（drill-down）；文件：插入 @path 并加空格闭合提及（原型同款）
  const tail = entry.dir ? '/' : ' ';
  emit('update:modelValue', props.modelValue.replace(/@[^\s]*$/, `@${entry.path}${tail}`));
}

/** 提及高亮（@ 文件 · # MCP · / 技能）：textarea 文字透明 + 底层高亮垫层（overlay 法，同主流编辑器） */
function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
const TOK_AT = 'rounded bg-blue-500/10 text-blue-600';
const TOK_MCP = 'rounded bg-purple-500/10 text-purple-600';
const TOK_SKILL = 'rounded bg-amber-500/15 text-amber-700';
const draftHtml = computed(() =>
  escapeHtml(props.modelValue).replace(
    /(^|\s)(@[^\s]+|#[\w-]+)|^\/[\w-]+/gm,
    (m, lead: string | undefined, tok: string | undefined) => {
      const cls = tok?.startsWith('@') ? TOK_AT : tok ? TOK_MCP : TOK_SKILL;
      return tok !== undefined ? `${lead ?? ''}<span class="${cls}">${tok}</span>` : `<span class="${cls}">${m}</span>`;
    },
  ),
);
const backdropRef = ref<HTMLElement | null>(null);
function syncScroll(e: Event): void {
  const ta = e.target as HTMLTextAreaElement;
  if (backdropRef.value) backdropRef.value.scrollTop = ta.scrollTop;
}

/** 多模态图片附件：本地暂存，随 send 一并上交后清空（≤4 张，单张原图 ≤4.5MB，与后端 AskPayload 校验对齐） */
const MAX_IMAGES = 4;
const MAX_IMAGE_BYTES = 4.5 * 1024 * 1024;
const attachments = ref<ChatImage[]>([]);
const imageError = ref('');
const fileInput = ref<HTMLInputElement | null>(null);

function previewUrl(img: ChatImage): string {
  return `data:${img.mime};base64,${img.dataBase64}`;
}
function addImageFiles(files: File[] | FileList): void {
  imageError.value = '';
  const list = Array.from(files).filter((f) => f.type.startsWith('image/'));
  for (const f of list) {
    if (attachments.value.length >= MAX_IMAGES) { imageError.value = `最多 ${MAX_IMAGES} 张图片`; return; }
    if (f.size > MAX_IMAGE_BYTES) { imageError.value = `「${f.name || '图片'}」超过 4.5MB，已跳过`; continue; }
    const reader = new FileReader();
    reader.onload = () => {
      const url = String(reader.result ?? '');
      const dataBase64 = url.slice(url.indexOf(',') + 1); // 去掉 data:<mime>;base64, 前缀
      if (dataBase64) attachments.value.push({ mime: f.type || 'image/png', dataBase64 });
    };
    reader.readAsDataURL(f);
  }
}
/** 粘贴：剪贴板含图片（截图 Ctrl+V）时拦下默认文本粘贴，转为附件 */
function onPaste(e: ClipboardEvent): void {
  const items = e.clipboardData?.items;
  if (!items) return;
  const files: File[] = [];
  for (const it of items) {
    if (it.type.startsWith('image/')) { const f = it.getAsFile(); if (f) files.push(f); }
  }
  if (files.length > 0) { e.preventDefault(); addImageFiles(files); }
}
function onDrop(e: DragEvent): void {
  const files = e.dataTransfer?.files;
  if (files && files.length > 0) addImageFiles(files);
}
function pickImages(): void { fileInput.value?.click(); }
function onFilePick(e: Event): void {
  const input = e.target as HTMLInputElement;
  if (input.files && input.files.length > 0) addImageFiles(input.files);
  input.value = ''; // 清空以允许再次选择同一文件
}
function removeImage(i: number): void { attachments.value.splice(i, 1); }
/** 发送：与父级 onSend 同条件——无文字不发（也不清空图片，避免误清用户已贴的图）；有文字则上交图片并清空 */
function doSend(): void {
  if (!props.modelValue.trim()) return;
  emit('send', [...attachments.value]);
  attachments.value = [];
  imageError.value = '';
}

/** 输入框键盘路由：菜单打开时 ↑↓/回车/Esc 接管，否则回车发送（Shift+回车换行） */
function onKey(e: KeyboardEvent): void {
  const menuLen =
    skillMenu.value.length > 0 ? skillMenu.value.length
    : mcpMenu.value.length > 0 ? mcpMenu.value.length
    : fileMenu.value.length;
  if (menuLen > 0) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIdx.value = (activeIdx.value + 1) % menuLen;
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIdx.value = (activeIdx.value - 1 + menuLen) % menuLen;
      return;
    }
    if (e.key === 'Escape') {
      menuDismissed.value = true;
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (skillMenu.value.length > 0) {
        pickSkill(skillMenu.value[activeIdx.value]!.name);
      } else if (mcpMenu.value.length > 0) {
        const item = mcpMenu.value[activeIdx.value];
        if (item?.connected) pickMcp(item.name); // 未连接项回车无效（置灰）
      } else {
        const file = fileMenu.value[activeIdx.value];
        if (file) pickFile(file);
      }
      return;
    }
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    doSend();
  }
}
</script>

<template>
  <div
    class="w-full bg-card border border-border focus-within:border-accent/50 focus-within:shadow-glow rounded-2xl p-4 shadow-popover transition-std space-y-3 relative"
    @drop.prevent="onDrop"
    @dragover.prevent
  >
    <!-- P4：/ 技能菜单（键入 / 时弹出，↑↓ 选择、回车确认、Esc 关闭） -->
    <div v-if="skillMenu.length > 0" class="absolute bottom-full mb-2 left-4 w-80 bg-card border border-border rounded-xl shadow-popover p-1 text-xs z-30">
      <div class="px-2.5 py-1.5 text-[10px] text-stone-500 font-semibold">技能 · ↑↓ 选择 · 回车确认 · Esc 关闭</div>
      <div
        v-for="(s, i) in skillMenu"
        :key="s.name"
        :class="['px-2.5 py-2 rounded-lg cursor-pointer transition-std flex items-center gap-2', i === activeIdx ? 'bg-cardHover' : 'hover:bg-cardHover']"
        @click="pickSkill(s.name)"
        @mouseenter="activeIdx = i"
      >
        <span class="font-mono font-semibold text-accent shrink-0">/{{ s.name }}</span>
        <span class="text-[10px] text-stone-600 truncate" :title="s.description">{{ s.description }}</span>
      </div>
    </div>
    <!-- P5：# MCP 连接器菜单（键入 # 时弹出；未连接置灰） -->
    <div v-if="mcpMenu.length > 0" class="absolute bottom-full mb-2 left-4 w-96 bg-card border border-border rounded-xl shadow-popover p-1 text-xs z-30">
      <div class="px-2.5 py-1.5 text-[10px] text-stone-500 font-semibold">MCP 连接器 · ↑↓ 选择 · 回车确认 · Esc 关闭</div>
      <div
        v-for="(s, i) in mcpMenu"
        :key="s.name"
        :class="['px-2.5 py-2 rounded-lg transition-std flex items-center gap-2',
          s.connected ? 'cursor-pointer' : 'opacity-50 cursor-not-allowed',
          i === activeIdx ? 'bg-cardHover' : 'hover:bg-cardHover']"
        @click="s.connected && pickMcp(s.name)"
        @mouseenter="activeIdx = i"
      >
        <span class="w-5 h-5 rounded bg-surface border border-border flex items-center justify-center overflow-hidden shrink-0">
          <img v-if="s.icon" :src="s.icon" class="w-full h-full object-cover" alt="" />
          <span v-else class="text-purple-700" v-html="ico('plug')" />
        </span>
        <span class="font-mono font-semibold text-purple-700 shrink-0">#{{ s.name }}</span>
        <span class="text-[10px] text-stone-600 truncate" :title="s.description">{{ s.description || '—' }}</span>
        <span v-if="!s.connected" class="ml-auto text-[9px] text-stone-400 shrink-0">未连接</span>
      </div>
    </div>
    <!-- 工作区条目菜单（键入 @ 时弹出，文件夹 + 文件，子串匹配） -->
    <div v-if="fileMenu.length > 0" class="absolute bottom-full mb-2 left-4 w-96 bg-card border border-border rounded-xl shadow-popover p-1 text-xs z-30">
      <div class="px-2.5 py-1.5 text-[10px] text-stone-500 font-semibold">提及工作区文件 · ↑↓ 选择 · 回车确认 · Esc 关闭</div>
      <div
        v-for="(f, i) in fileMenu"
        :key="f.path"
        :class="['px-2.5 py-2 rounded-lg cursor-pointer transition-std flex items-center gap-2', i === activeIdx ? 'bg-cardHover' : 'hover:bg-cardHover']"
        @click="pickFile(f)"
        @mouseenter="activeIdx = i"
      >
        <span :class="f.dir ? 'text-amber-500' : 'text-stone-500'" class="shrink-0" v-html="ico(f.dir ? 'folder' : 'file')" />
        <span class="font-mono text-[11px] truncate text-stone-800">@{{ f.path }}</span>
        <span v-if="f.dir" class="ml-auto text-[9px] text-stone-400 shrink-0">文件夹</span>
      </div>
    </div>
    <!-- 多模态图片预览行：缩略图 + 悬停删除；有附件才显示 -->
    <div v-if="attachments.length > 0" class="flex flex-wrap items-center gap-2">
      <div
        v-for="(img, i) in attachments"
        :key="i"
        class="relative group w-16 h-16 rounded-lg overflow-hidden border border-border bg-surface shrink-0"
      >
        <img :src="previewUrl(img)" class="w-full h-full object-cover" alt="图片附件" />
        <button
          class="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-black/60 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-std"
          title="移除图片"
          @click="removeImage(i)"
        ><span class="scale-[0.7]" v-html="ico('x')" /></button>
      </div>
    </div>
    <div v-if="imageError" class="text-[10px] text-rose-600">{{ imageError }}</div>

    <!-- 提及高亮：垫层渲染彩色 token，textarea 文字透明仅保留光标（字体度量须与垫层完全一致） -->
    <div class="relative">
      <div
        ref="backdropRef"
        aria-hidden="true"
        class="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-[13px] leading-relaxed text-stone-900"
        v-html="draftHtml"
      ></div>
      <textarea
        :value="modelValue"
        rows="3"
        :disabled="disabled"
        placeholder="今天帮你做什么？@ 选文件/文件夹 · # 调 MCP · / 调技能 · 可粘贴/拖入图片"
        class="relative w-full bg-transparent text-transparent caret-stone-900 placeholder-stone-400 outline-none resize-none leading-relaxed text-[13px] break-words"
        @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
        @keydown="onKey"
        @paste="onPaste"
        @scroll="syncScroll"
      />
    </div>

    <div class="flex items-center justify-between pt-2.5 border-t border-border">
      <div class="flex items-center gap-2">
        <!-- 多模态：添加图片（点击选择；也可直接 Ctrl+V 粘贴或拖拽图片到输入卡） -->
        <button
          class="flex items-center justify-center w-8 h-8 rounded-lg text-stone-500 hover:bg-cardHover hover:text-stone-800 transition-std disabled:opacity-40 disabled:cursor-not-allowed"
          title="添加图片（也可直接粘贴 Ctrl+V 或拖拽到此处，最多 4 张）"
          :disabled="disabled"
          @click="pickImages"
        ><span v-html="ico('image')" /></button>
        <input ref="fileInput" type="file" accept="image/*" multiple class="hidden" @change="onFilePick" />
        <!-- 工作区下拉切换器：选历史工作区 / 新建（选择文件夹） -->
        <div class="relative" ref="wsMenuRef">
          <button
            class="flex items-center gap-1.5 bg-surface hover:bg-cardHover border border-border hover:border-borderLight rounded-lg px-2.5 py-1.5 text-[11px] text-stone-700 transition-std"
            :title="activeRoot ?? '选择工作区文件夹'"
            @click="showWsMenu = !showWsMenu"
          >
            <span class="text-amber-700/80" v-html="ico('folder')" />
            <span class="font-mono max-w-[130px] truncate">{{ workspaceName || '选择工作区文件夹' }}</span>
            <span class="text-[8px] text-stone-400 transition-transform duration-200" :class="showWsMenu ? 'rotate-180' : ''">▼</span>
          </button>
          <div v-if="showWsMenu" class="absolute bottom-full mb-2 left-0 w-80 bg-card border border-border rounded-xl shadow-popover p-1 text-xs z-30">
            <div class="px-2.5 py-1.5 text-[10px] text-stone-500 font-semibold">切换工作区</div>
            <div v-if="roots.length === 0" class="px-2.5 py-2 text-[10px] text-stone-400">暂无历史工作区，选择下方文件夹开始</div>
            <div
              v-for="r in roots"
              :key="r"
              class="group flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer transition-std hover:bg-cardHover"
              :class="r === activeRoot ? 'text-stone-900' : 'text-stone-700'"
              :title="r"
              @click="pickRoot(r)"
            >
              <span class="text-amber-700/80 shrink-0" v-html="ico('folder')" />
              <span class="min-w-0 flex-1">
                <span class="block font-mono text-[11px] truncate">{{ nameOf(r) }}</span>
                <span class="block font-mono text-[9px] text-stone-400 truncate">{{ r }}</span>
              </span>
              <span v-if="r === activeRoot" class="text-accent shrink-0" title="当前工作区" v-html="ico('check')" />
              <button
                class="hidden group-hover:inline text-stone-400 hover:text-rose-600 shrink-0"
                title="移除关联目录"
                v-html="ico('x')"
                @click.stop="removeRoot(r)"
              />
            </div>
            <div v-if="roots.length > 0" class="my-1 border-t border-border" />
            <div
              class="px-2.5 py-2 rounded-lg cursor-pointer transition-std hover:bg-cardHover flex items-center gap-2 text-stone-700"
              @click="newWorkspace"
            >
              <span class="text-stone-500 shrink-0" v-html="ico('plus')" />
              <span class="text-[11px]">选择工作区文件夹…</span>
            </div>
          </div>
        </div>

        <!-- Chat / Agent 模式切换（Claude 同款） -->
        <div class="flex items-center bg-surface border border-border rounded-lg p-0.5">
          <button
            :class="['px-2.5 py-1 rounded-md text-[11px] font-medium transition-std', chatMode === 'chat' ? 'bg-card text-stone-900 shadow-sm' : 'text-stone-500 hover:text-stone-700']"
            @click="chatMode = 'chat'"
          >Chat</button>
          <button
            :class="['px-2.5 py-1 rounded-md text-[11px] font-medium transition-std', chatMode === 'agent' ? 'bg-card text-stone-900 shadow-sm' : 'text-stone-500 hover:text-stone-700']"
            @click="chatMode = 'agent'"
          >Agent</button>
        </div>

        <!-- 工作区默认权限（仅 Agent 模式；P3 三档可切换，立即生效） -->
        <div v-if="chatMode === 'agent'" class="relative">
          <button
            :class="['flex items-center gap-1.5 border rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-std', modeMeta(permMode).btn]"
            title="工作区默认权限"
            @click="showPermMenu = !showPermMenu"
          >
            <span v-html="ico('shield')" /> {{ permMode }}
          </button>
          <div v-if="showPermMenu" class="absolute bottom-full mb-2 left-0 w-72 bg-card border border-border rounded-xl shadow-popover p-1 text-xs z-30">
            <div class="px-2.5 py-1.5 text-[10px] text-stone-500 font-semibold">工作区默认权限（立即生效）</div>
            <div
              v-for="opt in PERM_OPTIONS"
              :key="opt.v"
              :class="['px-2.5 py-2 hover:bg-cardHover rounded-lg cursor-pointer transition-std flex items-start gap-2', permMode === opt.v ? 'text-stone-900' : 'text-stone-700']"
              @click="emit('select-mode', opt.v); showPermMenu = false"
            >
              <span class="font-mono font-semibold shrink-0" :class="opt.tag">{{ opt.v }}</span>
              <span class="text-[10px] text-stone-600 leading-relaxed">{{ opt.d }}</span>
            </div>
          </div>
        </div>
        <span v-else class="text-[10px] text-stone-400">Chat 模式不调用工具</span>
      </div>

      <div class="flex items-center gap-2.5">
        <!-- 模型下拉：在「模型配置」中新增/切换 -->
        <div class="relative">
          <select
            :value="modelId"
            :disabled="models.length === 0"
            class="appearance-none bg-surface border border-border hover:border-borderLight rounded-lg pl-2 pr-6 py-1.5 text-[10px] font-mono text-stone-600 outline-none cursor-pointer transition-std max-w-[160px] truncate disabled:opacity-50 disabled:cursor-not-allowed"
            title="切换模型"
            @change="emit('select-model', ($event.target as HTMLSelectElement).value)"
          >
            <option v-if="models.length === 0" value="">未配置模型</option>
            <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}</option>
          </select>
          <span class="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-[8px] text-stone-400">▼</span>
        </div>
        <!-- 火力档位：一个滑块联动 contextWindow(8K→1M) 与 maxTokens(2K→32K)，拖到最大 = 火力全开 -->
        <div
          class="flex items-center gap-1 select-none"
          :title="`模型火力：拖动调整上下文窗口与单次输出上限\n当前 上下文 ${powerWindowLabel} · 输出 ${powerOutputLabel}\n拖到最大 = 尽量用满模型能力（超出真实上限由系统自动回退）`"
        >
          <span :class="powerMaxed ? 'text-accent' : 'text-stone-400'" v-html="ico('bolt')" />
          <input
            type="range"
            min="0"
            :max="POWER_MAX"
            step="1"
            v-model.number="localPower"
            :disabled="models.length === 0"
            class="w-16 accent-accent cursor-pointer align-middle disabled:opacity-40 disabled:cursor-not-allowed"
            @change="emit('set-power', localPower)"
          />
          <span
            class="text-[10px] font-mono tabular-nums w-8 text-right"
            :class="powerMaxed ? 'text-accent font-semibold' : 'text-stone-500'"
          >{{ powerWindowLabel }}</span>
        </div>
        <button
          v-if="busy"
          class="w-8 h-8 rounded-full bg-stone-400 hover:bg-stone-500 text-white flex items-center justify-center shadow-lg transition-std"
          title="停止生成"
          v-html="ico('x')"
          @click="emit('stop')"
        />
        <button
          v-else
          class="w-8 h-8 rounded-full bg-accent hover:bg-accentDim text-white flex items-center justify-center shadow-lg transition-std disabled:opacity-40 disabled:cursor-not-allowed"
          :disabled="disabled || !modelValue.trim()"
          v-html="ico('send')"
          @click="doSend"
        />
      </div>
    </div>
  </div>
</template>
