<script setup lang="ts">
/**
 * 对话视图（P2 三栏工作台）：中栏消息流 + 右栏工作台（Diff/代码/文件）。
 * 事件驱动（AGENTS §18）：diff_ready → 右栏自动打开；权限内联确认卡（原型同款）。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import type { ChatMessage, Expert, McpServerView, ModelConfig, PermissionMode, SkillMeta, TreeNode, WorkspaceEntry } from '@agentbuddy/shared';
import { agent } from '../api/bridge';
import { useAgent } from '../composables/useAgent';
import { useSettings } from '../composables/useSettings';
import { useWorkbench } from '../composables/useWorkbench';
import { ico } from '../ui/icons';
import { bindCounts, bindTitle } from '../ui/expertLabel';
import { extractPreviewPaths } from '../ui/previewKind';
import { contextWindowToLevel, DEFAULT_LEVEL, levelToContextWindow, levelToMaxTokens } from '../ui/modelPower';
import ComposerCard from '../components/ComposerCard.vue';
import PermissionCard from '../components/PermissionCard.vue';
import ToolCard from '../components/ToolCard.vue';
import MarkdownBody from '../components/MarkdownBody.vue';
import WorkbenchPanel from '../components/workbench/WorkbenchPanel.vue';

const props = defineProps<{ sessionId: string | null; workspaceName: string; workspaceRoots: string[]; workspaceActive: string | null; expert?: Expert | null }>();
const emit = defineEmits<{ (e: 'pick-workspace'): void; (e: 'select-workspace-root', path: string): void; (e: 'remove-workspace-root', path: string): void; (e: 'workspace-changed'): void; (e: 'back-to-experts'): void; (e: 'rollback-done', branchSessionId: string): void; (e: 'session-cleared'): void }>();

const { messages, busy, thinking, error, notice, openSession, send, stop, pendingPermission, resolvePermission, diffSignal, streamingId } = useAgent();

const sessionRef = computed(() => props.sessionId);
/** 右栏工作台：接受/撤销后通知外层刷新顶栏 git 状态 */
const bench = useWorkbench(sessionRef, () => emit('workspace-changed'));

const draft = ref('');
/** 模型配置清单（含 contextWindow/maxTokens）：对话框下拉切换 + 火力档位滑块的读写源 */
const modelConfigs = ref<ModelConfig[]>([]);
/** 下拉只需 id/name */
const models = computed(() => modelConfigs.value.map((m) => ({ id: m.id, name: m.name })));
const modelId = ref('');
/** 当前激活模型完整配置（火力档位滑块据此定位与写回） */
const activeModel = computed(() => modelConfigs.value.find((m) => m.id === modelId.value) ?? null);
/** 火力档位（0..POWER_MAX）：由当前模型 contextWindow 反推初始位置 */
const powerLevel = computed(() => (activeModel.value ? contextWindowToLevel(activeModel.value.contextWindow) : DEFAULT_LEVEL));
const messageList = ref<HTMLElement | null>(null);

/** P4：启用技能清单（/ 菜单 + /name 触发校验）；键入 / 时刷新 */
const skillList = ref<SkillMeta[]>([]);
/** P7：专家会话时 / 菜单只列绑定技能（与 Main 侧 ask 硬边界同源）；普通会话全量启用技能 */
const enabledSkills = computed(() => {
  const all = skillList.value.filter((s) => s.enabled);
  const bound = props.expert?.skills ?? [];
  return bound.length > 0 && props.expert ? all.filter((s) => bound.includes(s.name)) : all;
});
async function loadSkills(): Promise<void> {
  const res = await agent().skills.list();
  if (res.ok && res.data) skillList.value = res.data;
}

/** P7 横幅绑定摘要：单行高度只放计数徽标（hover 看全量清单），长绑定不撑高横幅 */
const expertBind = computed(() => (props.expert ? { ...bindCounts(props.expert), title: bindTitle(props.expert) } : null));
watch(draft, (v) => {
  if (v.startsWith('/')) void loadSkills(); // 技能可能在管理页变更，键入时低成本刷新（非轮询）
  if (/(^|\s)@/.test(v)) void loadFiles(); // @ 文件提及：键入时拉取最新树（Agent 可能刚新建文件）
});

/** 工作区条目清单（@ 菜单）：层级序展平（浅层条目优先，避免深层目录链霸屏） */
const fileList = ref<WorkspaceEntry[]>([]);
function flattenFiles(nodes: TreeNode[]): WorkspaceEntry[] {
  const out: WorkspaceEntry[] = [];
  let level = nodes;
  while (level.length > 0) {
    const next: TreeNode[] = [];
    for (const n of level) {
      out.push({ path: n.path, dir: n.dir });
      if (n.dir) next.push(...(n.children ?? []));
    }
    level = next;
  }
  return out;
}
async function loadFiles(): Promise<void> {
  const res = await agent().workspace.tree();
  if (res.ok && res.data) fileList.value = flattenFiles(res.data);
}
// 多工作区：关联目录/活动目录变化后 @ 菜单清单随之刷新（事件驱动，不轮询）
watch(() => props.workspaceName, () => void loadFiles());

/** P5：MCP 连接器清单（# 菜单）；初始拉取 + stream:mcp 事件驱动更新（§18） */
const mcpServers = ref<Array<{ name: string; description: string; connected: boolean; icon?: string }>>([]);
function applyMcpViews(views: McpServerView[]): void {
  mcpServers.value = views.map((v) => ({
    name: v.config.name,
    description: v.config.description ?? '',
    connected: v.status === 'connected',
    icon: v.config.icon,
  }));
}
async function loadMcp(): Promise<void> {
  const res = await agent().mcp.list();
  if (res.ok && res.data) applyMcpViews(res.data);
}
let offMcpStream: (() => void) | null = null;

// 快捷入口：通用任务示例（点击整句填入输入框作为起点，用户再补充细节 / @ 文件）
const quickPresets = [
  { icon: 'file', label: '总结这份文档的要点' },
  { icon: 'folder', label: '整理文件夹里的资料' },
  { icon: 'search', label: '解释这段代码' },
  { icon: 'terminal', label: '写一个自动化脚本' },
];

watch(
  () => props.sessionId,
  (id) => {
    bench.reset();
    if (id) {
      void openSession(id);
      void bench.refresh(); // 回放场景：恢复审阅清单（工具卡片状态依赖）
    }
  },
  { immediate: true },
);

// diff_ready → 右栏自动打开并选中该变更（P2 任务 2）
watch(diffSignal, (sig) => {
  if (sig) {
    void bench.openDiff(sig.changeId);
    emit('workspace-changed'); // 落盘后顶栏脏文件数随之变化
  }
});

/** 回合结束自动弹出预览：从最后一条助手回复识别产出文件路径（贴合「模型说可预览」）；
 * 每个路径每会话仅自动弹一次，避免重复打扰 */
const autoPreviewed = new Set<string>();
watch(busy, (now, prev) => {
  if (prev !== true || now !== false) return;
  const last = [...messages.value].reverse().find((m) => m.role === 'assistant' && m.content);
  if (!last) return;
  for (const p of extractPreviewPaths(last.content)) {
    if (autoPreviewed.has(p)) continue;
    autoPreviewed.add(p);
    bench.openPreview(p);
    return; // 每回合最多自动弹一个
  }
});

// 自动滚动按帧合并：token 高频到达时每帧至多一次 scrollTo，避免逐 token 强制同步布局（读 scrollHeight）抖动
let scrollRaf: number | undefined;
function scheduleScroll(): void {
  if (scrollRaf !== undefined) return;
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = undefined;
    messageList.value?.scrollTo({ top: messageList.value.scrollHeight });
  });
}
watch([messages, thinking], () => void nextTick(scheduleScroll), { deep: true });

onMounted(async () => {
  await loadModels();
  await loadSettings();
  await loadSkills();
  await loadMcp();
  void loadFiles();
  offMcpStream = agent().onStream((event) => {
    if (event.type === 'mcp') applyMcpViews(event.servers);
  });
});

onUnmounted(() => {
  offMcpStream?.();
  if (scrollRaf !== undefined) cancelAnimationFrame(scrollRaf);
});

/** 模型列表 + 当前激活项（模型配置中心维护，对话框下拉切换） */
async function loadModels(): Promise<void> {
  const list = await agent().config.listModels();
  if (list.ok && list.data) modelConfigs.value = list.data;
  const active = await agent().config.getModel();
  if (active.ok && active.data) modelId.value = active.data.id;
}

async function onSelectModel(id: string): Promise<void> {
  const res = await agent().config.setActive(id);
  if (res.ok) modelId.value = id;
  else error.value = res.error ?? '切换模型失败';
}

/** 火力档位滑块：松手后把档位翻译成 contextWindow/maxTokens 写入当前模型。
 * 复用 setModel（apiKey 传空串 = 保留已存密钥，见 ipc.ts modelConfigSet）；
 * 档位高于模型真实上限由 orchestrator 的 400 自愈兜底，无需在此感知真实窗口。 */
async function onSetPower(level: number): Promise<void> {
  const cur = activeModel.value;
  if (!cur) return;
  const contextWindow = levelToContextWindow(level);
  const maxTokens = levelToMaxTokens(level);
  if (contextWindow === cur.contextWindow && maxTokens === cur.maxTokens) return;
  const res = await agent().config.setModel({
    id: cur.id,
    name: cur.name,
    provider: cur.provider,
    baseUrl: cur.baseUrl,
    model: cur.model,
    apiKey: '',
    encrypted: cur.encrypted,
    temperature: cur.temperature,
    contextWindow,
    maxTokens,
  });
  if (res.ok && res.data) {
    // 就地替换该条，activeModel/powerLevel 随之刷新（无需整表重载）
    const saved = res.data;
    modelConfigs.value = modelConfigs.value.map((m) => (m.id === saved.id ? saved : m));
  } else {
    error.value = res.error ?? '调整模型档位失败';
  }
}

/** P3：工作区默认权限（盾牌三档）—— 顶栏 chip 同源同步，持久化后下一轮 ask 立即生效 */
const { permMode, loadSettings, setMode } = useSettings();
async function onSelectMode(mode: PermissionMode): Promise<void> {
  const err = await setMode(mode);
  if (err) error.value = err;
}

function applyPreset(label: string): void {
  // 通用引导语：整句填入输入框，用户接着补充细节或 @ 具体文件（不再硬绑定特定技能/MCP 名）
  draft.value = label;
}

/** 动作行（Streaming Text 同款）：回复完成后淡入的复制按钮，短暂反馈「已复制」 */
const copiedId = ref('');
async function copyReply(m: ChatMessage): Promise<void> {
  await navigator.clipboard.writeText(m.content);
  copiedId.value = m.id;
  setTimeout(() => { if (copiedId.value === m.id) copiedId.value = ''; }, 1500);
}

/** 消息操作：撤回 = 删该条及之后、内容回填输入框；重发 = 撤回后原重发；删除 = 删单条。
 * 操作后从盘重载会话对齐 messages 与 todos（SessionStore 单一事实来源）；生成中 Main 侧拒绝。 */
async function withdraw(m: ChatMessage): Promise<void> {
  if (!props.sessionId || busy.value) return;
  const res = await agent().session.truncateFrom(props.sessionId, m.id);
  if (!res.ok) {
    error.value = res.error ?? '撤回失败';
    return;
  }
  draft.value = m.content;
  await openSession(props.sessionId);
}

async function resend(m: ChatMessage): Promise<void> {
  if (!props.sessionId || busy.value) return;
  const res = await agent().session.truncateFrom(props.sessionId, m.id);
  if (!res.ok) {
    error.value = res.error ?? '重发失败';
    return;
  }
  await openSession(props.sessionId);
  await send(m.content);
}

async function deleteMessage(m: ChatMessage): Promise<void> {
  if (!props.sessionId || busy.value) return;
  const res = await agent().session.deleteMessage(props.sessionId, m.id);
  if (!res.ok) {
    error.value = res.error ?? '删除失败';
    return;
  }
  await openSession(props.sessionId);
}

/** 清空当前会话：移除全部消息与 todos（保留会话壳，可继续对话）。影响面大故二次确认；
 * 成功后重置右栏工作台、从盘重载对齐 messages/todos，并通知上层刷新侧栏（标题已复位「新会话」）。生成中 Main 侧拒绝。 */
async function clearSession(): Promise<void> {
  if (!props.sessionId || busy.value) return;
  const ok = window.confirm('清空当前会话的全部消息？此操作不可恢复（会话本身会保留，可继续对话）。');
  if (!ok) return;
  const res = await agent().session.clear(props.sessionId);
  if (!res.ok) {
    error.value = res.error ?? '清空失败';
    return;
  }
  bench.reset();
  await openSession(props.sessionId);
  emit('session-cleared');
}

/** P2 3.3 节点回溯：仅 assistant 节点、且其后还有消息时可回（回到此处 = 抹掉之后的一切重来）。 */
function canRollbackHere(m: ChatMessage): boolean {
  if (m.role !== 'assistant' || busy.value) return false;
  const idx = messages.value.findIndex((x) => x.id === m.id);
  return idx >= 0 && idx < messages.value.length - 1;
}

/** 回到此处重来：强制还原该节点之后的全部工作区改动（含已接受、不可逆）+ 从该节点分叉新会话。
 * 影响面大，故 window.confirm 二次确认；成功后交由上层切到分支会话并刷新侧栏。 */
async function rollbackToHere(m: ChatMessage): Promise<void> {
  if (!props.sessionId || busy.value) return;
  const ok = window.confirm('回到此处将撤销该节点之后的全部改动（含已接受的文件变更，且不可恢复），并从此处新建一个分支会话继续。确定继续？');
  if (!ok) return;
  const res = await agent().session.rollback(props.sessionId, m.id);
  if (!res.ok || !res.data) {
    error.value = res.error ?? '回溯失败';
    return;
  }
  emit('rollback-done', res.data.branchSessionId);
}

/** Tool Chips 整组折叠：连续 tool 消息合并为一组（≥2 条显示组头部「N 次工具调用」） */
interface GroupItem { kind: 'group'; key: string; msgs: ChatMessage[] }
interface SingleItem { kind: 'single'; msg: ChatMessage }
type RenderItem = GroupItem | SingleItem;

const renderItems = computed<RenderItem[]>(() => {
  const items: RenderItem[] = [];
  let buf: ChatMessage[] = [];
  const flush = (): void => {
    if (buf.length) items.push({ kind: 'group', key: buf[0]!.id, msgs: buf });
    buf = [];
  };
  for (const m of messages.value) {
    if (m.role === 'tool') { buf.push(m); continue; }
    // 纯 toolCalls 无文字的 assistant 消息：不渲染，也不打断工具组（回放与实时保持一致的整组折叠）
    if (m.role === 'assistant' && !m.content) continue;
    flush();
    items.push({ kind: 'single', msg: m });
  }
  flush();
  return items;
});

const groupOverrides = ref<Record<string, boolean>>({});

/** 默认开合：活跃回合（流式中）或组内存在待审阅变更 → 展开；历史回合默认折叠；手动点击覆盖 */
function groupOpen(item: GroupItem): boolean {
  const o = groupOverrides.value[item.key];
  if (o !== undefined) return o;
  const lastId = messages.value.at(-1)?.id;
  if (busy.value && item.msgs.some((m) => m.id === lastId)) return true;
  return item.msgs.some((m) => m.toolChangeId && bench.reviewStatus(m.toolChangeId) === 'pending');
}

function toggleGroup(item: GroupItem): void {
  groupOverrides.value[item.key] = !groupOpen(item);
}

/** 工具组头部摘要：组内工具/技能名去重串联（技能显示「技能 /name」、MCP 显示 server/tool），
 * 一眼看清这组做了什么；超长截断。 */
function groupLabels(msgs: ChatMessage[]): string {
  const seen: string[] = [];
  for (const m of msgs) {
    const name = m.toolName ?? '';
    let label = name;
    if (name === 'use_skill') {
      let skill = '';
      try {
        const a = JSON.parse(m.toolArgs ?? '{}') as Record<string, unknown>;
        if (typeof a['name'] === 'string') skill = (a['name'] as string).replace(/^\//, '').trim();
      } catch {
        /* 入参解析失败则退化为「技能」 */
      }
      label = skill ? `技能 /${skill}` : '技能';
    } else {
      const mm = /^mcp__([^_].*?)__(.+)$/.exec(name);
      if (mm) label = `${mm[1]}/${mm[2]}`;
    }
    if (label && !seen.includes(label)) seen.push(label);
  }
  const joined = seen.join(' · ');
  return joined.length > 60 ? `${joined.slice(0, 60)}…` : joined;
}

/** P4：/name 触发——命中启用技能则随 ask 传 skillName（正文作为高优先级指令注入） */
async function onSend(): Promise<void> {
  const text = draft.value.trim();
  if (!text) return;
  const m = /^\/([\w-]+)(?:\s|$)/.exec(text);
  if (m) {
    const matched = enabledSkills.value.find((s) => s.name === m[1]);
    if (!matched) {
      error.value = `未知或已禁用的技能 /${m[1]}，可在「技能 Skills」页查看`;
      return;
    }
    draft.value = '';
    await send(text, matched.name);
    return;
  }
  draft.value = '';
  await send(text);
}
</script>

<template>
  <div class="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">

    <!-- P7：专家会话横幅（返回专家团 + 头像/名称/标签 + 绑定明细） -->
    <div v-if="expert" class="h-11 px-4 border-b border-border bg-surface/60 flex items-center gap-2.5 shrink-0">
      <button
        class="flex items-center gap-1 text-[11px] text-stone-500 hover:text-stone-800 transition-std shrink-0"
        title="返回专家团（会话保留，可从侧栏「专家会话」或卡片再次进入）"
        @click="emit('back-to-experts')"
      >
        <span class="rotate-90 inline-block" v-html="ico('chevron')" /> 专家团
      </button>
      <span class="w-6 h-6 rounded-lg bg-card border border-border flex items-center justify-center overflow-hidden text-[13px] shrink-0">
        <img v-if="expert.logo" :src="expert.logo" class="w-full h-full object-cover" alt="" />
        <span v-else>{{ expert.emoji }}</span>
      </span>
      <span class="font-semibold text-stone-900 text-[12px] shrink-0">{{ expert.name }}</span>
      <span
        v-for="t in expert.tags.slice(0, 3)"
        :key="t"
        class="px-1.5 py-px rounded-full bg-accent/10 text-accent border border-accent/25 text-[9px] font-medium shrink-0"
      >{{ t }}</span>
      <span class="ml-auto flex items-center gap-1 shrink-0" :title="expertBind?.title">
        <span v-if="expertBind?.builtin" class="px-1.5 py-px rounded-md font-mono text-[9px] bg-blue-500/10 text-blue-700 border border-blue-500/25 shrink-0">{{ expertBind.builtin }} 工具</span>
        <span v-if="expertBind?.mcp" class="px-1.5 py-px rounded-md font-mono text-[9px] bg-purple-500/10 text-purple-700 border border-purple-500/25 shrink-0">{{ expertBind.mcp }} MCP</span>
        <span v-if="expertBind?.skills" class="px-1.5 py-px rounded-md font-mono text-[9px] bg-indigo-500/10 text-indigo-700 border border-indigo-500/25 shrink-0">{{ expertBind.skills }} 技能</span>
        <span v-if="expertBind && !expertBind.builtin && !expertBind.mcp && !expertBind.skills" class="text-[9.5px] text-stone-400 shrink-0">全量工具与技能</span>
      </span>
    </div>

    <div class="flex-1 flex min-w-0 min-h-0 overflow-hidden">

    <!-- 中栏：消息流 + 输入 -->
    <div class="flex-1 flex flex-col min-w-0 overflow-hidden">

      <!-- 场景 A：首页（大输入框，无场景分类 Tab） -->
      <div v-if="messages.length === 0" class="flex-1 flex flex-col items-center justify-center px-6 -mt-10 max-w-3xl mx-auto w-full space-y-7 overflow-y-auto">

        <div class="text-center space-y-2.5">
          <img src="img/logo.png" class="w-11 h-11 mx-auto rounded-2xl shadow-glow mb-1" alt="AgentBuddy" />
          <h1 class="text-[28px] font-serif font-bold tracking-tight text-stone-900">AgentBuddy, 我帮你</h1>
          <p class="text-stone-500 text-[12px]">直接描述你想做什么，Agent 自动选择工具与技能 · 办公文档 / 资料整理 / 日常问答 / 编程开发</p>
        </div>

        <!-- 快捷入口：通用任务示例 -->
        <div class="flex flex-wrap items-center justify-center gap-2 max-w-xl">
          <button
            v-for="preset in quickPresets"
            :key="preset.label"
            class="bg-card hover:bg-cardHover border border-border hover:border-borderLight px-3 py-1.5 rounded-full text-stone-700 flex items-center gap-1.5 transition-std text-[11px] shadow-card"
            @click="applyPreset(preset.label)"
          >
            <span class="text-stone-500" v-html="ico(preset.icon)" />
            <span>{{ preset.label }}</span>
          </button>
        </div>

        <div v-if="error" class="w-full flex items-center justify-between bg-rose-50 border border-rose-500/30 rounded-lg px-3 py-2 text-[11px] text-rose-600">
          <span class="flex items-center gap-1.5"><span v-html="ico('alert')" /> {{ error }}</span>
          <button class="text-stone-400 hover:text-stone-600" v-html="ico('x')" @click="error = ''" />
        </div>

        <!-- P1 2.3：非致命提醒（如 MCP 工具超额丢弃）——琥珀横幅，不打断回合 -->
        <div v-if="notice" class="w-full flex items-center justify-between bg-amber-50 border border-amber-500/30 rounded-lg px-3 py-2 text-[11px] text-amber-700">
          <span class="flex items-center gap-1.5"><span v-html="ico('alert')" /> {{ notice }}</span>
          <button class="text-stone-400 hover:text-stone-600" v-html="ico('x')" @click="notice = ''" />
        </div>

        <ComposerCard
          v-model="draft"
          :busy="busy"
          :disabled="!sessionId"
          :workspace-name="workspaceName"
          :roots="workspaceRoots"
          :active-root="workspaceActive"
          :models="models"
          :model-id="modelId"
          :power="powerLevel"
          :perm-mode="permMode"
          :skills="enabledSkills"
          :servers="mcpServers"
          :files="fileList"
          @send="onSend"
          @stop="stop"
          @pick-workspace="emit('pick-workspace')"
          @select-root="(p) => emit('select-workspace-root', p)"
          @remove-root="(p) => emit('remove-workspace-root', p)"
          @select-model="(id) => void onSelectModel(id)"
          @set-power="(lv) => void onSetPower(lv)"
          @select-mode="(m) => void onSelectMode(m)"
        />

        <!-- Auto 模式边界说明 -->
        <p class="text-[10px] text-stone-400 leading-relaxed text-center max-w-lg">
          Auto 模式仅自动执行：读取文件、修改工作区文件、白名单低风险命令（如测试）。
          高风险命令、网络操作与删除类操作（rm / git reset --hard / docker rm…）任何模式下都需要你确认。
        </p>
      </div>

      <!-- 场景 B：对话流 + 底部输入卡 -->
      <template v-else>
        <!-- 会话顶部工具条：清空当前会话（右对齐，生成中禁用；不可恢复故点击二次确认） -->
        <div class="flex items-center justify-end px-6 pt-3 shrink-0">
          <button
            class="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] text-stone-400 hover:bg-stone-500/5 hover:text-rose-600 transition-std disabled:opacity-40 disabled:pointer-events-none"
            title="清空当前会话的全部消息（会话保留，可继续对话）"
            :disabled="busy"
            @click="() => void clearSession()"
          >
            <span v-html="ico('trash')" /> 清空会话
          </button>
        </div>
        <div ref="messageList" class="flex-1 overflow-y-auto px-6 py-5 space-y-4">

          <template v-for="item in renderItems" :key="item.key">
            <!-- 工具组（≥2 条）：组头部「N 次工具调用」+ 整组折叠（Tool Chips 同款） -->
            <div v-if="item.kind === 'group' && item.msgs.length > 1" class="pl-10 -my-1 min-w-0">
              <button
                class="-mx-1.5 flex w-fit max-w-full items-center gap-1.5 rounded-lg px-1.5 py-1 text-[11.5px] text-stone-600 hover:bg-stone-500/5 transition-std"
                :title="groupOpen(item) ? '收起工具调用' : '展开工具调用'"
                @click="toggleGroup(item)"
              >
                <span class="transition-std shrink-0" :class="groupOpen(item) ? 'rotate-0' : '-rotate-90'" v-html="ico('chevron')" />
                <span class="tabular-nums shrink-0">{{ item.msgs.length }} 次工具调用</span>
                <span v-if="groupLabels(item.msgs)" class="truncate font-mono text-[11px] text-stone-500">· {{ groupLabels(item.msgs) }}</span>
              </button>
              <div
                class="grid transition-all duration-300"
                :style="{ gridTemplateRows: groupOpen(item) ? '1fr' : '0fr', opacity: groupOpen(item) ? 1 : 0 }"
              >
                <div class="min-h-0 overflow-hidden">
                  <div class="flex flex-col gap-1 pb-1">
                    <ToolCard
                      v-for="m in item.msgs"
                      :key="m.id"
                      :msg="m"
                      :review-status="bench.reviewStatus(m.toolChangeId)"
                      @view-diff="(id) => void bench.openDiff(id)"
                    />
                  </div>
                </div>
              </div>
            </div>

            <!-- 单条工具：不显示组头部，直接出紧凑行 -->
            <div v-else-if="item.kind === 'group'" class="pl-10 -my-1.5 min-w-0">
              <ToolCard
                :msg="item.msgs[0]!"
                :review-status="bench.reviewStatus(item.msgs[0]!.toolChangeId)"
                @view-diff="(id) => void bench.openDiff(id)"
              />
            </div>

            <!-- 用户消息：右对齐（主流 Agent 同款）；悬停出撤回 / 重发 / 删除 -->
            <div v-else-if="item.msg.role === 'user'" class="flex items-start justify-end gap-1 group">
              <div class="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity duration-200 shrink-0">
                <button
                  class="flex h-6 items-center gap-1 px-1.5 rounded-md text-[10px] text-stone-400 hover:bg-stone-500/5 hover:text-stone-600 transition-std"
                  title="撤回：删除该条及之后的对话，内容回填输入框"
                  @click="() => void withdraw(item.msg)"
                >
                  <span v-html="ico('undo')" /> 撤回
                </button>
                <button
                  class="flex h-6 items-center gap-1 px-1.5 rounded-md text-[10px] text-stone-400 hover:bg-stone-500/5 hover:text-stone-600 transition-std"
                  title="重发：删除之后的对话并重新发送该消息"
                  @click="() => void resend(item.msg)"
                >
                  <span v-html="ico('refresh')" /> 重发
                </button>
                <button
                  class="flex w-6 h-6 items-center justify-center rounded-md text-stone-400 hover:bg-stone-500/5 hover:text-rose-600 transition-std"
                  title="删除消息"
                  @click="() => void deleteMessage(item.msg)"
                >
                  <span v-html="ico('trash')" />
                </button>
              </div>
              <div class="bg-stone-800 text-stone-50 rounded-xl px-3.5 py-2.5 text-[12.5px] leading-relaxed max-w-2xl shadow-card whitespace-pre-wrap select-text">{{ item.msg.content }}</div>
            </div>

            <!-- assistant 消息：仅渲染文字内容；工具调用统一由 ToolCard 呈现（避免名称重复占空间）；
                 纯 toolCalls 无文字的消息不占行，流式等待时末条显示 caret -->
            <div v-else-if="item.msg.content || item.msg.reasoning || item.msg.id === streamingId" class="flex items-start gap-3">
              <div class="w-7 h-7 rounded-full overflow-hidden shrink-0 shadow-sm" :class="expert ? 'bg-card border border-border flex items-center justify-center text-[14px]' : ''">
                <img v-if="expert?.logo" :src="expert.logo" class="w-full h-full object-cover" :alt="expert.name" />
                <span v-else-if="expert">{{ expert.emoji }}</span>
                <img v-else src="img/logo.png" class="w-full h-full object-cover" alt="AI" />
              </div>
              <div class="max-w-3xl space-y-1.5 min-w-0">
                <!-- 推理模型思维链：灰色折叠「思考过程」，流式中自动展开、结束后可回看；与正式回答视觉分离 -->
                <details v-if="item.msg.reasoning" class="mb-0.5" :open="item.msg.id === streamingId">
                  <summary class="cursor-pointer select-none text-[11px] text-stone-400 hover:text-stone-600 transition-std">思考过程</summary>
                  <div class="mt-1 pl-2.5 border-l-2 border-stone-200 text-[11.5px] leading-relaxed text-stone-400 whitespace-pre-wrap select-text">{{ item.msg.reasoning }}</div>
                </details>
                <div v-if="item.msg.content" class="bg-card border border-border rounded-xl px-3.5 py-2.5 text-stone-800 shadow-card select-text">
                  <MarkdownBody :content="item.msg.content" :streaming="item.msg.id === streamingId" />
                </div>
                <!-- 动作行：流式结束后才可用（复制），与 Streaming Text 的 actions 淡入一致 -->
                <div
                  v-if="item.msg.content"
                  class="flex items-center gap-0.5 -ml-1 transition-opacity duration-300"
                  :class="item.msg.id === streamingId ? 'opacity-0 pointer-events-none' : 'opacity-100'"
                >
                  <button
                    class="flex w-6 h-6 items-center justify-center rounded-md text-stone-400 hover:bg-stone-500/5 hover:text-stone-600 transition-std"
                    :title="copiedId === item.msg.id ? '已复制' : '复制回复'"
                    @click="() => void copyReply(item.msg)"
                  >
                    <span v-html="copiedId === item.msg.id ? ico('check') : ico('copy')" />
                  </button>
                  <button
                    v-if="canRollbackHere(item.msg)"
                    class="flex w-6 h-6 items-center justify-center rounded-md text-stone-400 hover:bg-stone-500/5 hover:text-amber-600 transition-std"
                    title="回到此处重来（撤销之后改动并分叉新会话）"
                    @click="() => void rollbackToHere(item.msg)"
                  >
                    <span v-html="ico('history')" />
                  </button>
                  <button
                    class="flex w-6 h-6 items-center justify-center rounded-md text-stone-400 hover:bg-stone-500/5 hover:text-rose-600 transition-std"
                    title="删除消息"
                    @click="() => void deleteMessage(item.msg)"
                  >
                    <span v-html="ico('trash')" />
                  </button>
                </div>
                <span v-else class="stream-caret is-streaming" />
              </div>
            </div>
          </template>

          <!-- P2 任务 6：权限内联确认卡（琥珀色，消息流末尾） -->
          <PermissionCard
            v-if="pendingPermission"
            :pending="pendingPermission"
            @resolve="(allow, remember) => void resolvePermission(allow, remember)"
          />

          <!-- 思考中等待态：发送后等首字 / 工具执行完等下一轮（主流 Agent 同款） -->
          <div v-if="busy && thinking" class="flex items-start gap-3">
            <div class="w-7 h-7 rounded-full overflow-hidden shrink-0 shadow-sm" :class="expert ? 'bg-card border border-border flex items-center justify-center text-[14px]' : ''">
              <img v-if="expert?.logo" :src="expert.logo" class="w-full h-full object-cover" :alt="expert.name" />
              <span v-else-if="expert">{{ expert.emoji }}</span>
              <img v-else src="img/logo.png" class="w-full h-full object-cover" alt="AI" />
            </div>
            <div class="flex items-center gap-2 bg-card border border-border rounded-xl px-3.5 py-2.5 shadow-card">
              <span class="text-[11px] text-stone-500">思考中</span>
              <span class="flex gap-1"><span class="thinking-dot" /><span class="thinking-dot" /><span class="thinking-dot" /></span>
            </div>
          </div>
        </div>

        <div class="px-6 pb-5 pt-1 space-y-2">
          <div v-if="error" class="flex items-center justify-between bg-rose-50 border border-rose-500/30 rounded-lg px-3 py-2 text-[11px] text-rose-600">
            <span class="flex items-center gap-1.5"><span v-html="ico('alert')" /> {{ error }}</span>
            <button class="text-stone-400 hover:text-stone-600" v-html="ico('x')" @click="error = ''" />
          </div>

          <!-- P1 2.3：非致命提醒（如 MCP 工具超额丢弃）——琥珀横幅，不打断回合 -->
          <div v-if="notice" class="flex items-center justify-between bg-amber-50 border border-amber-500/30 rounded-lg px-3 py-2 text-[11px] text-amber-700">
            <span class="flex items-center gap-1.5"><span v-html="ico('alert')" /> {{ notice }}</span>
            <button class="text-stone-400 hover:text-stone-600" v-html="ico('x')" @click="notice = ''" />
          </div>

          <ComposerCard
            v-model="draft"
            :busy="busy"
            :disabled="!sessionId"
            :workspace-name="workspaceName"
            :roots="workspaceRoots"
            :active-root="workspaceActive"
            :models="models"
            :model-id="modelId"
            :power="powerLevel"
            :perm-mode="permMode"
            :skills="enabledSkills"
            :servers="mcpServers"
            :files="fileList"
            @send="onSend"
            @stop="stop"
            @pick-workspace="emit('pick-workspace')"
            @select-root="(p) => emit('select-workspace-root', p)"
            @remove-root="(p) => emit('remove-workspace-root', p)"
            @select-model="(id) => void onSelectModel(id)"
            @set-power="(lv) => void onSetPower(lv)"
            @select-mode="(m) => void onSelectMode(m)"
          />
        </div>
      </template>
    </div>

    <!-- 右栏：Diff / 代码 / 文件 工作台（P2 任务 1/2/3/7） -->
    <WorkbenchPanel v-if="bench.visible.value" :store="bench" />
    </div>
  </div>
</template>
