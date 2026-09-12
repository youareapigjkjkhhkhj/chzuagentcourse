<script setup lang="ts">
/**
 * P5 MCP 连接器管理页（原型同款卡片式）：
 * 名称 / 类型徽标 / 状态 / Tools 数与展开 / 命令行；连接开关、重连、编辑、删除。
 * 新增弹窗支持「常规连接 ↔ JSON 导入」双通道切换；支持上传连接器图标（data URL）。
 * 状态更新事件驱动（§18）：订阅 stream:event 的 mcp 广播，不轮询。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue';
import type { McpServerView } from '@agentbuddy/shared';
import { agent } from '../api/bridge';
import { useOverlayDismiss } from '../composables/useOverlayDismiss';
import { ico } from '../ui/icons';

const servers = ref<McpServerView[]>([]);
const search = ref('');
const err = ref('');
const notice = ref('');
const expanded = ref<Record<string, boolean>>({});
const busyName = ref('');

/** 新增 / 编辑弹窗：常规表单 ↔ JSON 粘贴 双模式切换（用户要求） */
const showModal = ref(false);
const modalMode = ref<'form' | 'json'>('form');
const editingName = ref<string | null>(null); // null = 新增
const form = ref(emptyForm());
const formErr = ref('');
const modalBusy = ref(false);
const jsonText = ref('');
const jsonErr = ref('');

/** 遮罩点击关闭：按下与抬起都在遮罩才关，避免弹窗内拖选文本（复制 JSON / 命令行）松手越界误关 */
const overlay = useOverlayDismiss(() => { showModal.value = false; });

function emptyForm(): {
  name: string;
  type: 'stdio' | 'http' | 'sse';
  command: string;
  argsText: string;
  envText: string;
  url: string;
  headersText: string;
  description: string;
  icon: string;
  enabled: boolean;
  alwaysLoad: boolean;
} {
  return { name: '', type: 'stdio', command: '', argsText: '', envText: '', url: '', headersText: '', description: '', icon: '', enabled: true, alwaysLoad: false };
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase();
  if (!q) return servers.value;
  return servers.value.filter((s) => s.config.name.toLowerCase().includes(q) || (s.config.description ?? '').toLowerCase().includes(q));
});

/** 已连接工具总数（仅展示）：实际下发由 bus 按 schema 规模在常驻 / 按需间分流，并非全量随会话下发 */
const mountedTools = computed(() => servers.value.filter((s) => s.status === 'connected').reduce((n, s) => n + s.tools.length, 0));

let unsubscribe: (() => void) | null = null;

async function load(): Promise<void> {
  const res = await agent().mcp.list();
  if (res.ok && res.data) servers.value = res.data;
  else err.value = res.error ?? '加载连接器失败';
}

onMounted(async () => {
  await load();
  // 状态变化（连接中 → 已连接 / 崩溃离线）由 Main 广播，不轮询（§18）
  unsubscribe = agent().onStream((event) => {
    if (event.type === 'mcp') servers.value = event.servers;
  });
});
onUnmounted(() => unsubscribe?.());

/* ── 弹窗：常规表单 ── */

function openCreate(): void {
  editingName.value = null;
  form.value = emptyForm();
  formErr.value = '';
  jsonText.value = '';
  jsonErr.value = '';
  modalMode.value = 'form';
  showModal.value = true;
}

function openEdit(view: McpServerView): void {
  const c = view.config;
  editingName.value = c.name;
  form.value = {
    name: c.name,
    type: c.type,
    command: c.command ?? '',
    argsText: (c.args ?? []).join('\n'),
    envText: c.env && Object.keys(c.env).length > 0 ? JSON.stringify(c.env, null, 2) : '',
    url: c.url ?? '',
    headersText: c.headers && Object.keys(c.headers).length > 0 ? JSON.stringify(c.headers, null, 2) : '',
    description: c.description ?? '',
    icon: c.icon ?? '',
    enabled: c.enabled,
    alwaysLoad: c.alwaysLoad ?? false,
  };
  formErr.value = '';
  jsonText.value = '';
  jsonErr.value = '';
  modalMode.value = 'form';
  showModal.value = true;
}

/** 图标上传：读为 data URL，原图 ≤100KB，仅接受 image/* */
async function onIconPick(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    formErr.value = '图标必须为图片文件';
    return;
  }
  if (file.size > 100 * 1024) {
    formErr.value = '图标过大（上限 100KB）';
    return;
  }
  form.value.icon = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error('读取失败'));
    reader.readAsDataURL(file);
  }).catch(() => '');
  if (!form.value.icon) formErr.value = '图标读取失败';
}

/** 常规表单提交：前端必填校验 → IPC zod 复核 → 保存即连接（启用时） */
async function submitForm(): Promise<void> {
  const f = form.value;
  formErr.value = '';
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$/.test(f.name)) {
    formErr.value = '名称须为 1–32 位字母/数字/下划线/中划线，且字母或数字开头';
    return;
  }
  if (f.type === 'stdio' && !f.command.trim()) {
    formErr.value = '请填写启动命令（如 npx / uvx / node）';
    return;
  }
  if (f.type !== 'stdio' && !f.url.trim()) {
    formErr.value = '请填写端点 URL';
    return;
  }
  let env: Record<string, string> | undefined;
  if (f.envText.trim()) {
    try {
      const parsed: unknown = JSON.parse(f.envText);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('须为对象');
      for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
        if (typeof v !== 'string') throw new Error(`${k} 的值必须为字符串`);
      }
      env = parsed as Record<string, string>;
    } catch (e) {
      formErr.value = `环境变量 JSON 非法：${e instanceof Error ? e.message : String(e)}`;
      return;
    }
  }
  let headers: Record<string, string> | undefined;
  if (f.type !== 'stdio' && f.headersText.trim()) {
    try {
      const parsed: unknown = JSON.parse(f.headersText);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('须为对象');
      for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
        if (typeof v !== 'string') throw new Error(`${k} 的值必须为字符串`);
      }
      headers = parsed as Record<string, string>;
    } catch (e) {
      formErr.value = `请求头 JSON 非法：${e instanceof Error ? e.message : String(e)}`;
      return;
    }
  }
  const args = f.argsText.split('\n').map((s) => s.trim()).filter(Boolean);

  modalBusy.value = true;
  const res = await agent().mcp.upsert({
    name: f.name,
    type: f.type,
    command: f.type === 'stdio' ? f.command.trim() : undefined,
    args: f.type === 'stdio' && args.length > 0 ? args : undefined,
    env,
    url: f.type !== 'stdio' ? f.url.trim() : undefined,
    headers,
    description: f.description.trim() || undefined,
    enabled: f.enabled,
    alwaysLoad: f.alwaysLoad,
    icon: f.icon || undefined,
  });
  modalBusy.value = false;
  if (!res.ok) {
    formErr.value = res.error ?? '保存失败';
    return;
  }
  if (res.data) servers.value = res.data;
  showModal.value = false;
  notice.value = editingName.value ? `连接器 ${f.name} 已保存` : `连接器 ${f.name} 已添加${f.enabled ? '，正在连接…' : ''}`;
}

/** JSON 粘贴导入：行级报错整体拒绝；成功返回导入名单 */
async function submitJson(): Promise<void> {
  jsonErr.value = '';
  if (!jsonText.value.trim()) {
    jsonErr.value = '请粘贴 mcpServers JSON';
    return;
  }
  modalBusy.value = true;
  const res = await agent().mcp.importJson(jsonText.value);
  modalBusy.value = false;
  if (!res.ok) {
    jsonErr.value = res.error ?? '导入失败';
    return;
  }
  if (res.data) servers.value = res.data.views;
  showModal.value = false;
  notice.value = `已导入 ${res.data.imported.length} 个连接器：${res.data.imported.join('、')}`;
}

/* ── 卡片操作 ── */

async function toggleEnabled(view: McpServerView): Promise<void> {
  busyName.value = view.config.name;
  const res = await agent().mcp.setEnabled(view.config.name, !view.config.enabled);
  busyName.value = '';
  if (res.ok && res.data) servers.value = res.data;
  else err.value = res.error ?? '操作失败';
}

/** 强制常驻开关：仅切换 alwaysLoad 标志（不重连）；下一轮会话构建工具总线时生效 */
async function toggleAlwaysLoad(view: McpServerView): Promise<void> {
  busyName.value = view.config.name;
  const res = await agent().mcp.setAlwaysLoad(view.config.name, !view.config.alwaysLoad);
  busyName.value = '';
  if (res.ok && res.data) servers.value = res.data;
  else err.value = res.error ?? '操作失败';
}

async function reconnect(view: McpServerView): Promise<void> {
  busyName.value = view.config.name;
  const res = await agent().mcp.reconnect(view.config.name);
  busyName.value = '';
  if (res.ok && res.data) servers.value = res.data;
  else err.value = res.error ?? '重连失败';
}

async function removeServer(view: McpServerView): Promise<void> {
  if (!window.confirm(`确定删除连接器 ${view.config.name} 吗？配置将被移除，不可恢复。`)) return;
  const res = await agent().mcp.remove(view.config.name);
  if (res.ok && res.data) servers.value = res.data;
  else err.value = res.error ?? '删除失败';
}

/** 状态徽标文案 / 配色 */
const STATUS_META: Record<string, { label: string; cls: string; dot: string }> = {
  connected: { label: '已连接', cls: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/25', dot: 'bg-emerald-500' },
  connecting: { label: '连接中', cls: 'bg-amber-500/10 text-amber-700 border-amber-500/25', dot: 'bg-amber-500 animate-pulse' },
  offline: { label: '离线', cls: 'bg-rose-500/10 text-rose-600 border-rose-500/25', dot: 'bg-rose-500' },
  disabled: { label: '已停用', cls: 'bg-surface text-stone-500 border-border', dot: 'bg-stone-300' },
};

function commandLine(view: McpServerView): string {
  const c = view.config;
  if (c.type !== 'stdio') return c.url ?? '';
  return [c.command ?? '', ...(c.args ?? [])].join(' ');
}
</script>

<template>
  <div class="flex-1 overflow-y-auto p-6 space-y-4 w-full">
    <div class="space-y-1">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-serif font-bold text-stone-900 flex items-center gap-2">
          <span class="text-purple-700" v-html="ico('plug')" /> MCP 连接器
        </h2>
        <div class="flex items-center gap-3">
          <input
            v-model="search"
            placeholder="搜索连接器..."
            class="w-44 bg-card border border-border focus:border-accent/50 rounded-lg px-3 py-1.5 text-[11px] outline-none text-stone-800 placeholder-stone-400 transition-std"
          />
          <button
            class="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg text-[11px] font-medium transition-std shadow-sm"
            @click="openCreate"
          >
            <span v-html="ico('plus')" /> 新增连接器
          </button>
        </div>
      </div>
      <p class="text-[11px] text-stone-500 leading-relaxed max-w-4xl">
        按 MCP 协议接入外部工具（stdio / http / sse 三种传输）。配置存于
        <span class="font-mono text-[10px] bg-surface px-1 rounded border border-border">~/.AgentBuddy/mcp.json</span>
        （兼容 Claude Desktop 格式 JSON 导入）；工具以
        <span class="font-mono text-[10px] bg-surface px-1 rounded border border-border">NETWORK</span>
        风险接入，首次调用需确认（可按连接器记住）；输入框键入
        <span class="font-mono text-[10px] bg-surface px-1 rounded border border-border">#</span> 提及连接器。
      </p>
    </div>

    <div v-if="notice" class="flex items-center justify-between bg-emerald-50 border border-emerald-500/30 rounded-lg px-3 py-2 text-[11px] text-emerald-700">
      <span class="flex items-center gap-1.5"><span v-html="ico('check')" /> {{ notice }}</span>
      <button class="text-stone-400 hover:text-stone-600" v-html="ico('x')" @click="notice = ''" />
    </div>
    <div v-if="err" class="flex items-center justify-between bg-rose-50 border border-rose-500/30 rounded-lg px-3 py-2 text-[11px] text-rose-600">
      <span class="flex items-center gap-1.5"><span v-html="ico('alert')" /> {{ err }}</span>
      <button class="text-stone-400 hover:text-stone-600" v-html="ico('x')" @click="err = ''" />
    </div>

    <!-- 已连接工具数：小规模全量常驻，schema 合计超阈值转按需（search_tools 检索发现）；标「常驻」的连接器强制全量下发 -->
    <div class="flex items-center gap-1.5 rounded-lg px-3 py-2 text-[11px] border bg-surface border-border text-stone-500">
      <span v-html="ico('check')" />
      <span>已挂载 MCP 工具 {{ mountedTools }} 个。规模较小时全量随会话下发；合计过大时自动转「按需加载」（模型经 search_tools 检索命中后调用），标「常驻」的连接器强制全量下发。</span>
    </div>

    <!-- 卡片列表 -->
    <div v-if="filtered.length === 0" class="text-center text-stone-400 text-[11px] py-10">
      暂无连接器。点击「新增连接器」用表单添加，或切到 JSON 模式粘贴 Claude Desktop 格式的 <span class="font-mono">mcpServers</span>。
    </div>
    <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
      <div
        v-for="view in filtered"
        :key="view.config.name"
        :class="['bg-card border rounded-xl p-3.5 space-y-2.5 shadow-card transition-std', view.config.enabled ? 'border-border' : 'border-border opacity-60']"
      >
        <!-- 头部：图标 + 名称 + 类型 + 状态 + 启停开关 -->
        <div class="flex items-center gap-2">
          <span class="w-8 h-8 rounded-lg bg-surface border border-border flex items-center justify-center overflow-hidden shrink-0">
            <img v-if="view.config.icon" :src="view.config.icon" class="w-full h-full object-cover" alt="" />
            <span v-else class="text-purple-700" v-html="ico('plug')" />
          </span>
          <span class="font-mono text-[12px] font-semibold text-stone-900 truncate">#{{ view.config.name }}</span>
          <span
            :class="['px-1.5 py-0.5 rounded-full text-[9.5px] font-mono font-medium border',
              view.config.type === 'stdio' ? 'bg-emerald-500/10 text-emerald-700 border-emerald-500/25' : 'bg-blue-500/10 text-blue-700 border-blue-500/25']"
          >{{ view.config.type.toUpperCase() }}</span>
          <span :class="['px-1.5 py-0.5 rounded-full text-[9.5px] font-medium border flex items-center gap-1', STATUS_META[view.status]!.cls]">
            <span :class="['w-1.5 h-1.5 rounded-full', STATUS_META[view.status]!.dot]" /> {{ STATUS_META[view.status]!.label }}
          </span>
          <span class="ml-auto flex items-center gap-2 shrink-0">
            <span v-if="view.status === 'connected'" class="text-[10px] text-stone-400 font-mono">{{ view.tools.length }} tools</span>
            <!-- 启停开关 -->
            <button
              :class="['w-8 h-[18px] rounded-full relative transition-std shrink-0', view.config.enabled ? 'bg-emerald-500' : 'bg-stone-300', busyName === view.config.name ? 'opacity-50' : '']"
              :title="view.config.enabled ? '停用（断开连接）' : '启用（自动连接）'"
              :disabled="busyName === view.config.name"
              @click="() => void toggleEnabled(view)"
            >
              <span :class="['absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white shadow transition-std', view.config.enabled ? 'left-[16px]' : 'left-[2px]']" />
            </button>
          </span>
        </div>

        <!-- 按需加载状态 + 强制常驻开关（仅已连接且有工具；独立整行，避免头部徽标拥挤溢出） -->
        <div v-if="view.status === 'connected' && view.tools.length > 0" class="flex items-center gap-2">
          <span
            :class="['px-1.5 py-0.5 rounded-full text-[9px] font-medium border shrink-0',
              view.config.alwaysLoad ? 'bg-purple-500/10 text-purple-700 border-purple-500/25'
                : view.onDemand ? 'bg-amber-500/10 text-amber-700 border-amber-500/25'
                : 'bg-surface text-stone-500 border-border']"
          >{{ view.config.alwaysLoad ? '常驻' : view.onDemand ? '按需' : '全量' }}</span>
          <span class="text-[10px] text-stone-500 truncate">
            {{ view.config.alwaysLoad ? '强制常驻中：工具参数始终随会话下发' : view.onDemand ? '按需加载：模型经 search_tools 检索命中后调用' : '工具规模较小：参数全量随会话下发' }}
          </span>
          <button
            :class="['ml-auto w-8 h-[18px] rounded-full relative transition-std shrink-0', view.config.alwaysLoad ? 'bg-purple-500' : 'bg-stone-300', busyName === view.config.name ? 'opacity-50' : '']"
            :title="view.config.alwaysLoad ? '取消强制常驻（恢复按需分流）' : '强制常驻（工具参数始终下发，跳过 search_tools 检索）'"
            :disabled="busyName === view.config.name"
            @click="() => void toggleAlwaysLoad(view)"
          >
            <span :class="['absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white shadow transition-std', view.config.alwaysLoad ? 'left-[16px]' : 'left-[2px]']" />
          </button>
        </div>

        <!-- 描述 / 命令 / env keys -->
        <p v-if="view.config.description" class="text-[11px] text-stone-600 leading-relaxed line-clamp-2" :title="view.config.description">
          {{ view.config.description }}
        </p>
        <div class="font-mono text-[10px] text-stone-500 bg-surface border border-border rounded-md px-2 py-1.5 truncate" :title="commandLine(view)">
          <span class="text-stone-400">{{ view.config.type === 'stdio' ? 'cmd' : 'url' }}</span> · {{ commandLine(view) || '—' }}
        </div>
        <div v-if="view.config.env && Object.keys(view.config.env).length > 0" class="text-[10px] text-stone-400 font-mono truncate">
          env：{{ Object.keys(view.config.env).join(', ') }}
        </div>

        <!-- 离线错误 -->
        <div v-if="view.error && view.status !== 'disabled'" class="flex items-start gap-1.5 text-[10.5px] text-rose-600 leading-relaxed">
          <span class="shrink-0 mt-px" v-html="ico('alert')" />
          <span class="break-all">{{ view.error }}</span>
        </div>

        <!-- Tools 展开区 -->
        <div v-if="expanded[view.config.name] && view.status === 'connected'" class="bg-surface border border-border rounded-md p-2 space-y-1 max-h-40 overflow-y-auto">
          <div v-if="view.tools.length === 0" class="text-[10px] text-stone-400">该 server 未暴露工具</div>
          <div v-for="t in view.tools" :key="t.name" class="text-[10.5px] leading-relaxed">
            <span class="font-mono font-semibold text-purple-700">{{ view.config.name }} / {{ t.name }}</span>
            <span v-if="t.description" class="text-stone-500"> — {{ t.description }}</span>
          </div>
        </div>

        <!-- 底部操作 -->
        <div class="flex items-center gap-2 pt-2 border-t border-border">
          <button
            v-if="view.status === 'connected'"
            class="flex-1 py-1.5 bg-surface hover:bg-cardHover text-stone-600 hover:text-purple-700 border border-border rounded-md text-[10px] transition-std"
            @click="expanded[view.config.name] = !expanded[view.config.name]"
          >{{ expanded[view.config.name] ? '收起 Tools' : '查看 Tools' }}</button>
          <button
            v-if="view.status === 'offline' && view.config.enabled"
            class="flex-1 py-1.5 bg-surface hover:bg-cardHover text-stone-600 hover:text-emerald-700 border border-border rounded-md text-[10px] transition-std"
            :disabled="busyName === view.config.name"
            @click="() => void reconnect(view)"
          >{{ busyName === view.config.name ? '重连中…' : '重连' }}</button>
          <button
            class="flex-1 py-1.5 bg-surface hover:bg-cardHover text-stone-600 hover:text-accent border border-border rounded-md text-[10px] transition-std"
            @click="openEdit(view)"
          >编辑</button>
          <button
            class="p-1.5 text-stone-400 hover:text-rose-600 hover:bg-rose-500/10 rounded-md transition-std"
            title="删除连接器"
            v-html="ico('trash')"
            @click="() => void removeServer(view)"
          />
        </div>
      </div>
    </div>

    <!-- ═══ 弹窗：新增 / 编辑（常规连接 ↔ JSON 导入 双通道切换） ═══ -->
    <div
      v-if="showModal"
      class="fixed inset-0 z-50 flex items-center justify-center modal-overlay"
      @mousedown="overlay.onOverlayDown"
      @click="overlay.onOverlayClick"
    >
      <div class="bg-card border border-border rounded-2xl shadow-popover w-full max-w-lg mx-4 overflow-hidden max-h-[85vh] flex flex-col" @click.stop>
        <div class="flex items-center justify-between px-6 py-4 border-b border-border">
          <h3 class="font-bold text-stone-900 flex items-center gap-2">
            <span class="text-purple-700" v-html="ico('plug')" />
            {{ editingName ? `编辑连接器 ${editingName}` : '新增连接器' }}
          </h3>
          <button class="text-stone-500 hover:text-stone-700 p-1" v-html="ico('x')" @click="showModal = false" />
        </div>

        <!-- 模式切换：常规连接 / JSON 导入（编辑时仅常规表单） -->
        <div v-if="!editingName" class="flex gap-2 px-6 pt-4">
          <button
            v-for="m in (['form', 'json'] as const)"
            :key="m"
            :class="['flex-1 py-2 rounded-lg text-[11px] font-medium transition-std border',
              modalMode === m ? 'bg-emerald-600/15 border-emerald-500/40 text-emerald-700' : 'bg-surface border-border text-stone-600 hover:border-borderLight']"
            @click="modalMode = m"
          >{{ m === 'form' ? '常规连接' : 'JSON 导入' }}</button>
        </div>

        <!-- 常规表单 -->
        <div v-if="modalMode === 'form'" class="p-6 space-y-4 overflow-y-auto">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-[11px] text-stone-600 mb-1.5">连接器名称 <span class="text-rose-600">*</span></label>
              <input
                v-model="form.name"
                placeholder="github / filesystem"
                :disabled="editingName !== null"
                class="w-full bg-surface border border-border focus:border-emerald-500/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 placeholder-stone-400 font-mono disabled:opacity-50"
              />
            </div>
            <div>
              <label class="block text-[11px] text-stone-600 mb-1.5">连接类型 <span class="text-rose-600">*</span></label>
              <div class="flex gap-2">
                <button
                  v-for="t in (['stdio', 'http', 'sse'] as const)"
                  :key="t"
                  :class="['flex-1 py-2 rounded-lg text-[11px] font-medium transition-std border font-mono',
                    form.type === t ? 'bg-emerald-600/20 border-emerald-500/50 text-emerald-700' : 'bg-surface border-border text-stone-600']"
                  :title="t === 'stdio' ? '本地进程（command + args）' : t === 'http' ? 'Streamable HTTP（主流网关 / Cocos Creator 等）' : '旧版 SSE 端点'"
                  @click="form.type = t"
                >{{ t.toUpperCase() }}</button>
              </div>
            </div>
          </div>

          <div v-if="form.type === 'stdio'" class="space-y-4 pl-4 border-l-2 border-emerald-500/30">
            <div>
              <label class="block text-[11px] text-stone-600 mb-1.5">启动命令 <span class="text-rose-600">*</span></label>
              <input
                v-model="form.command"
                placeholder="npx / uvx / node"
                class="w-full bg-surface border border-border focus:border-emerald-500/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 placeholder-stone-400 font-mono"
              />
            </div>
            <div>
              <label class="block text-[11px] text-stone-600 mb-1.5">参数 <span class="text-stone-400">(每行一个)</span></label>
              <textarea
                v-model="form.argsText"
                rows="3"
                placeholder="-y @modelcontextprotocol/server-filesystem /path"
                class="w-full bg-surface border border-border focus:border-emerald-500/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 placeholder-stone-400 resize-none font-mono"
              />
            </div>
          </div>
          <div v-else class="space-y-4 pl-4 border-l-2 border-blue-500/30">
            <div>
              <label class="block text-[11px] text-stone-600 mb-1.5">端点 URL <span class="text-rose-600">*</span></label>
              <input
                v-model="form.url"
                placeholder="http://127.0.0.1:3000/mcp"
                class="w-full bg-surface border border-border focus:border-accent/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 placeholder-stone-400 font-mono"
              />
              <p class="text-[10px] text-stone-400 mt-1">HTTP = Streamable HTTP（主流网关默认）；SSE = 旧版端点。保存后立即尝试连接。</p>
            </div>
            <div>
              <label class="block text-[11px] text-stone-600 mb-1.5">请求头 <span class="text-stone-400">(JSON，可选，值支持 ${VAR} 占位，如鉴权 Token)</span></label>
              <textarea
                v-model="form.headersText"
                rows="2"
                placeholder='{"Authorization": "Bearer ${MY_TOKEN}"}'
                class="w-full bg-surface border border-border focus:border-accent/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 placeholder-stone-400 resize-none font-mono"
              />
            </div>
          </div>

          <div>
            <label class="block text-[11px] text-stone-600 mb-1.5">描述</label>
            <input
              v-model="form.description"
              placeholder="该连接器提供的能力..."
              class="w-full bg-surface border border-border focus:border-emerald-500/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 placeholder-stone-400"
            />
          </div>

          <div>
            <label class="block text-[11px] text-stone-600 mb-1.5">环境变量 <span class="text-stone-400">(JSON，值支持 ${VAR} 占位，连接时注入，不写日志)</span></label>
            <textarea
              v-model="form.envText"
              rows="2"
              placeholder='{"GITHUB_TOKEN": "${GITHUB_TOKEN}"}'
              class="w-full bg-surface border border-border focus:border-emerald-500/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 placeholder-stone-400 resize-none font-mono"
            />
          </div>

          <!-- 图标上传 -->
          <div>
            <label class="block text-[11px] text-stone-600 mb-1.5">图标 <span class="text-stone-400">(可选，≤100KB 图片)</span></label>
            <div class="flex items-center gap-3">
              <span class="w-9 h-9 rounded-lg bg-surface border border-border flex items-center justify-center overflow-hidden shrink-0">
                <img v-if="form.icon" :src="form.icon" class="w-full h-full object-cover" alt="icon" />
                <span v-else class="text-stone-300" v-html="ico('plug')" />
              </span>
              <label
                class="flex items-center gap-1.5 bg-surface hover:bg-cardHover border border-border hover:border-borderLight rounded-lg px-3 py-1.5 text-[11px] text-stone-700 transition-std cursor-pointer"
              >
                <span v-html="ico('upload')" /> 上传图片
                <input type="file" accept="image/*" class="hidden" @change="(e) => void onIconPick(e)" />
              </label>
              <button
                v-if="form.icon"
                class="text-[11px] text-stone-400 hover:text-rose-600 transition-std"
                @click="form.icon = ''"
              >移除</button>
            </div>
          </div>

          <label class="flex items-center gap-2 text-[11px] text-stone-700 cursor-pointer select-none">
            <input v-model="form.enabled" type="checkbox" class="accent-emerald-600" />
            保存后立即连接（关闭则仅保存配置，可随时用开关启用）
          </label>

          <label class="flex items-start gap-2 text-[11px] text-stone-700 cursor-pointer select-none">
            <input v-model="form.alwaysLoad" type="checkbox" class="accent-purple-600 mt-0.5" />
            <span>强制常驻工具（跳过按需检索，参数始终随会话下发）；工具很多时会增大每次请求体积，通常保持关闭、由系统按 schema 规模自动分流。</span>
          </label>

          <p v-if="formErr" class="text-[11px] text-rose-600 flex items-start gap-1.5">
            <span class="shrink-0 mt-px" v-html="ico('alert')" /> {{ formErr }}
          </p>
        </div>

        <!-- JSON 粘贴导入 -->
        <div v-else class="p-6 space-y-3 overflow-y-auto">
          <p class="text-[11px] text-stone-500 leading-relaxed">
            兼容 Claude Desktop / Cursor 的
            <span class="font-mono text-stone-700">mcp.json</span>（<span class="font-mono text-stone-700">{"mcpServers": {...}}</span>、
            内层对象、或带 <span class="font-mono text-stone-700">name</span> 的单条配置对象均可），解析后批量合并，同名覆盖；<span class="font-mono text-stone-700">enabled: false</span>
            导入后保持未连接；<span class="font-mono text-stone-700">env</span> 中
            <span class="font-mono text-stone-700">${VAR}</span> 占位符连接时从系统环境变量注入。
          </p>
          <textarea
            v-model="jsonText"
            rows="12"
            spellcheck="false"
            class="w-full bg-surface border border-border focus:border-accent/50 rounded-lg px-3 py-2 text-[11px] font-mono outline-none text-stone-800 resize-none"
          />
          <p v-if="jsonErr" class="text-[11px] text-rose-600 whitespace-pre-wrap flex items-start gap-1.5">
            <span class="shrink-0 mt-px" v-html="ico('alert')" /> {{ jsonErr }}
          </p>
        </div>

        <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-border bg-surface">
          <button class="px-4 py-2 rounded-lg text-[11px] text-stone-600 hover:bg-cardHover transition-std" @click="showModal = false">取消</button>
          <button
            v-if="modalMode === 'form'"
            :disabled="modalBusy"
            class="px-4 py-2 rounded-lg text-[11px] font-medium bg-emerald-600 hover:bg-emerald-500 text-white shadow-sm transition-std disabled:opacity-50"
            @click="() => void submitForm()"
          >{{ modalBusy ? '保存中…' : editingName ? '保存' : '添加' }}</button>
          <button
            v-else
            :disabled="modalBusy"
            class="px-4 py-2 rounded-lg text-[11px] font-medium bg-accent hover:bg-accentDim text-white shadow-sm transition-std disabled:opacity-50"
            @click="() => void submitJson()"
          >{{ modalBusy ? '导入中…' : '批量导入' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
