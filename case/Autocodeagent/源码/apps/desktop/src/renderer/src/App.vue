<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import type { Expert, GitInfo, SessionMeta, SessionSearchHit, WorkspaceState } from '@agentbuddy/shared';
import { agent } from './api/bridge';
import { planTodos } from './composables/useAgent';
import { useSettings } from './composables/useSettings';
import { modeMeta } from './ui/permModes';
import ChatView from './views/ChatView.vue';
import ExpertsView from './views/ExpertsView.vue';
import McpView from './views/McpView.vue';
import SettingsView from './views/SettingsView.vue';
import SkillsView from './views/SkillsView.vue';
import UsageView from './views/UsageView.vue';
import { ico } from './ui/icons';

type View = 'assistant' | 'experts' | 'skills' | 'mcp' | 'models' | 'usage';

const navItems: Array<{ view: View; icon: string; label: string }> = [
  { view: 'assistant', icon: 'bot', label: 'AI 助理' },
  { view: 'experts', icon: 'users', label: '专家团' },
  { view: 'skills', icon: 'sparkle', label: '技能 Skills' },
  { view: 'mcp', icon: 'plug', label: 'MCP 连接器' },
  { view: 'models', icon: 'cpu', label: '模型配置' },
  { view: 'usage', icon: 'chart', label: '用量统计' },
];

const currentView = ref<View>('assistant');
const sessions = ref<SessionMeta[]>([]);
const activeSessionId = ref<string | null>(null);
/** 多工作区状态：roots = 已关联目录；active = 活动目录（顶栏 / git / 相对路径归属） */
const wsState = ref<WorkspaceState | null>(null);
const wsOpen = ref(true);
const roots = computed(() => wsState.value?.roots ?? []);
const workspacePath = computed(() => wsState.value?.active ?? null);
/** P4：执行计划侧栏面板开合（默认展开） */
const planOpen = ref(true);
const planDone = computed(() => planTodos.value.filter((t) => t.status === 'done').length);
/** P2 任务 1：顶栏二级状态条的 git 分支与脏文件数 */
const gitInfo = ref<GitInfo | null>(null);

const workspaceName = computed(() =>
  workspacePath.value ? workspacePath.value.split(/[\\/]/).filter(Boolean).pop() ?? '' : '',
);

/** P3：顶栏权限状态 chip（与盾牌弹层同源） */
const { permMode, loadSettings } = useSettings();

/* ── P7 专家团：专家清单 + 会话按 expertId 分组（专家会话不混入助理侧栏） ── */
const experts = ref<Expert[]>([]);
const expertOpen = ref<Record<string, boolean>>({});
const assistantSessions = computed(() => sessions.value.filter((s) => !s.expertId));
const expertSessionGroups = computed(() =>
  experts.value
    .map((e) => ({ expert: e, items: sessions.value.filter((s) => s.expertId === e.id) }))
    .filter((g) => g.items.length > 0),
);
const sessionCounts = computed<Record<string, number>>(() => {
  const m: Record<string, number> = {};
  for (const s of sessions.value) if (s.expertId) m[s.expertId] = (m[s.expertId] ?? 0) + 1;
  return m;
});
/** 当前会话绑定的专家（ChatView 横幅/头像）；专家已删除时回退普通会话形态 */
const activeExpert = computed(() => {
  const meta = sessions.value.find((s) => s.id === activeSessionId.value);
  return (meta?.expertId && experts.value.find((e) => e.id === meta.expertId)) || null;
});

async function loadExperts(): Promise<void> {
  const res = await agent().expert.list();
  if (res.ok && res.data) experts.value = res.data;
}

/** 点击专家卡片：有历史会话则恢复最近一个，否则新建绑定 expertId 的会话（ask 自动套用人设与绑定） */
async function openExpert(e: Expert): Promise<void> {
  const own = sessions.value.filter((s) => s.expertId === e.id).sort((a, b) => b.updatedAt - a.updatedAt);
  if (own.length > 0) {
    activeSessionId.value = own[0]!.id;
  } else {
    const res = await agent().session.create(e.name, e.id);
    if (!res.ok || !res.data) return;
    await refreshSessions();
    activeSessionId.value = res.data.id;
  }
  currentView.value = 'experts';
}

/** 删除专家：其历史会话降级为普通会话（expertId 悬空，ask 查无专家即回退全量）；
 * 主区判据是 activeExpert，删完自动从专家会话退回卡片列表，无需切视图。 */
async function onExpertRemoved(): Promise<void> {
  await Promise.all([loadExperts(), refreshSessions()]);
}

async function refreshSessions(): Promise<void> {
  const res = await agent().session.list();
  if (res.ok && res.data) sessions.value = res.data;
}

/** 切换 / 选择工作区后重定会话范围：list 已被 Main 按活动工作区过滤——
 * 当前会话仍属新范围则保持（重复选同一文件夹不跳走）；否则有会话开最近一个，
 * 无则自动新建空会话（相当于全新开始，对齐主流项目级隔离）。 */
async function rescopeSessions(): Promise<void> {
  const prev = activeSessionId.value;
  await refreshSessions();
  if (prev && sessions.value.some((s) => s.id === prev)) return;
  if (sessions.value.length === 0) {
    await createSession();
    return;
  }
  openSession(sessions.value[0]!.id);
}

/* ── P1 2.3：侧栏会话搜索（标题 + 消息内容全文 grep，Main 侧执行；200ms 防抖） ── */
const searchQuery = ref('');
const searchHits = ref<SessionSearchHit[]>([]);
let searchTimer: ReturnType<typeof setTimeout> | null = null;
watch(searchQuery, (q) => {
  if (searchTimer) clearTimeout(searchTimer);
  const query = q.trim();
  if (!query) {
    searchHits.value = [];
    return;
  }
  searchTimer = setTimeout(() => {
    void agent().session.search(query).then((res) => {
      if (res.ok && res.data) searchHits.value = res.data;
    });
  }, 200);
});

/** 点击搜索结果：打开会话并清空搜索（恢复树形列表） */
function openSearchHit(id: string): void {
  searchQuery.value = '';
  searchHits.value = [];
  openSession(id);
}

function expertNameOf(id?: string): string {
  return (id && experts.value.find((e) => e.id === id)?.name) || '';
}

/** P1 2.3：LLM 自动命名后刷新侧栏标题（事件驱动 §18，不轮询） */
let offTitleStream: (() => void) | null = null;

async function createSession(): Promise<void> {
  const res = await agent().session.create('新会话');
  if (res.ok && res.data) {
    await refreshSessions();
    activeSessionId.value = res.data.id;
    currentView.value = 'assistant';
  }
}

async function deleteSession(id: string): Promise<void> {
  await agent().session.delete(id);
  if (activeSessionId.value === id) activeSessionId.value = null;
  await refreshSessions();
}

async function selectWorkspace(): Promise<void> {
  const res = await agent().workspace.select();
  if (res.ok && res.data) {
    wsState.value = res.data;
    void refreshGit();
    await rescopeSessions();
  }
}

/** 多工作区：移除关联目录（会话不受影响） */
async function removeRoot(path: string): Promise<void> {
  const res = await agent().workspace.remove(path);
  if (res.ok && res.data) {
    wsState.value = res.data;
    void refreshGit();
    // 移除活动目录会回落到首个根 → 会话范围随之切换，需重定侧栏
    await rescopeSessions();
  }
}

/** 多工作区：切换活动目录（相对路径 / 命令 cwd / git 归属随之切换） */
async function setActiveRoot(path: string): Promise<void> {
  const res = await agent().workspace.setActive(path);
  if (res.ok && res.data) {
    wsState.value = res.data;
    wsOpen.value = true;
    void refreshGit();
    await rescopeSessions();
  }
}

function nameOf(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

/** 刷新顶栏 git 状态：工作区切换 / Agent 落盘变更 / 接受撤销后由事件驱动（§18，不轮询） */
async function refreshGit(): Promise<void> {
  const res = await agent().workspace.git();
  gitInfo.value = res.ok ? res.data ?? null : null;
}

function openSession(id: string): void {
  activeSessionId.value = id;
  // P7：专家会话从侧栏分组点开时切到专家视图（ChatView 复用，横幅/头像据 expert 展示）
  const meta = sessions.value.find((s) => s.id === id);
  currentView.value = meta?.expertId && experts.value.some((e) => e.id === meta.expertId) ? 'experts' : 'assistant';
}

/** P2 3.3 节点回溯完成：刷新侧栏纳入新分支 → 切到分支会话（复用 openSession 的视图路由）→
 * 工作区已被逆序回滚，刷新 git 状态。原会话保留在侧栏（时间旅行的原时间线）。 */
async function onRollbackDone(branchSessionId: string): Promise<void> {
  await refreshSessions();
  openSession(branchSessionId);
  void refreshGit();
}

/** 侧栏导航切换：activeSessionId 是跨视图共享的状态，必须按视图归位——
 * 否则从助理会话点「专家团」时活动会话仍在，主区会继续渲染 ChatView 而不是专家卡片页。 */
function goView(view: View): void {
  currentView.value = view;
  // 专家团入口 = 卡片列表；进专家会话走卡片或侧栏「专家会话」分组
  if (view === 'experts') {
    activeSessionId.value = null;
    return;
  }
  // 回到编程助理：恢复最近一个助理会话（无则置空，ChatView 走空态且输入框禁用）
  if (view === 'assistant' && (activeSessionId.value === null || activeExpert.value)) {
    activeSessionId.value =
      [...assistantSessions.value].sort((a, b) => b.updatedAt - a.updatedAt)[0]?.id ?? null;
  }
}

/** 应用菜单（main 经 stream:event 下发的 nav 事件）路由：新建/打开动作 + 六个视图直达 */
function onNav(view: string): void {
  if (view === 'new-session') { void createSession(); return; }
  if (view === 'pick-workspace') { void selectWorkspace(); return; }
  const VIEWS: View[] = ['assistant', 'experts', 'skills', 'mcp', 'models', 'usage'];
  if (VIEWS.includes(view as View)) goView(view as View);
}

onMounted(async () => {
  const ws = await agent().workspace.get();
  if (ws.ok && ws.data) wsState.value = ws.data;
  void refreshGit();
  await loadSettings();
  void loadExperts();

  await refreshSessions();
  if (sessions.value.length === 0) await createSession();
  else activeSessionId.value = sessions.value[0]?.id ?? null;

  // 自动标题落盘后刷新侧栏（title 事件全局订阅，与会话视图无关）
  offTitleStream = agent().onStream((event) => {
    if (event.type === 'title') void refreshSessions();
    else if (event.type === 'nav') onNav(event.view);
  });
});

onUnmounted(() => offTitleStream?.());
</script>

<template>
  <div class="flex h-screen w-screen flex-col bg-main text-stone-800 font-sans antialiased overflow-hidden select-none text-xs">

    <!-- 顶部应用标题栏 -->
    <header class="h-9 bg-sidebar border-b border-border flex items-center justify-between px-3 text-stone-600">
      <div class="flex items-center gap-3">
        <span class="font-semibold text-stone-900 tracking-tight flex items-center gap-2">
          <img src="img/logo.png" class="w-5 h-5 rounded-md shadow-sm" alt="logo" />
          <span>AgentBuddy</span>
          <span class="text-[10px] text-stone-500 font-normal">v0.1 · 本地轻量编程代理</span>
        </span>
      </div>
    </header>

    <!-- 主体容器 -->
    <div class="flex-1 flex overflow-hidden">

      <!-- 左侧导航与代码空间 -->
      <aside class="w-64 bg-sidebar border-r border-border flex flex-col justify-between shrink-0">
        <div class="flex-1 overflow-y-auto p-3 space-y-5">

          <div class="flex items-center justify-between px-1 text-stone-600">
            <span class="font-semibold text-stone-900 tracking-tight">工作台</span>
          </div>

          <!-- 新建会话 -->
          <button
            class="w-full bg-card hover:bg-cardHover text-stone-900 py-2 px-3 rounded-lg border border-border hover:border-borderLight flex items-center justify-center gap-2 font-medium shadow-card transition-std"
            @click="createSession"
          >
            <span v-html="ico('plus')" />
            <span>新建会话</span>
          </button>

          <!-- P1 2.3：会话搜索（标题 + 消息内容全文；输入即搜，200ms 防抖） -->
          <div class="relative">
            <span class="absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400 pointer-events-none" v-html="ico('search')" />
            <input
              v-model="searchQuery"
              type="text"
              placeholder="搜索会话标题与内容…"
              class="w-full bg-card border border-border rounded-lg pl-8 pr-7 py-1.5 text-[11px] text-stone-700 placeholder:text-stone-400 focus:outline-none focus:border-borderLight transition-std"
            />
            <button
              v-if="searchQuery"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-stone-400 hover:text-stone-600"
              title="清空搜索"
              v-html="ico('x')"
              @click="searchQuery = ''"
            />
          </div>
          <div v-if="searchQuery.trim()" class="space-y-0.5 -mt-3">
            <div class="px-2 text-[10px] text-stone-400">
              {{ searchHits.length > 0 ? `${searchHits.length} 个匹配会话` : '无匹配会话' }}
            </div>
            <div
              v-for="h in searchHits"
              :key="h.id"
              class="px-2 py-1.5 rounded-md text-[11px] cursor-pointer transition-std border"
              :class="activeSessionId === h.id
                ? 'bg-accent/10 border-accent/25'
                : 'border-transparent hover:bg-card'"
              @click="openSearchHit(h.id)"
            >
              <div class="flex items-center gap-1.5 text-stone-800">
                <span class="text-stone-400 shrink-0" v-html="ico('chat')" />
                <span class="truncate font-medium">{{ h.title }}</span>
                <span v-if="h.expertId" class="ml-auto px-1 py-px rounded bg-purple-500/10 text-purple-700 border border-purple-500/20 text-[9px] shrink-0">{{ expertNameOf(h.expertId) || '专家' }}</span>
              </div>
              <div class="pl-[18px] truncate text-[10px] text-stone-400 mt-0.5">{{ h.snippet }}</div>
            </div>
          </div>

          <!-- 核心功能导航（线性图标） -->
          <div class="space-y-0.5 text-stone-600">
            <div
              v-for="nav in navItems"
              :key="nav.view"
              class="relative flex items-center gap-2.5 px-2.5 py-[7px] rounded-md hover:bg-card hover:text-stone-800 cursor-pointer transition-std"
              :class="{ 'bg-card text-stone-900 font-medium shadow-sm': currentView === nav.view }"
              @click="goView(nav.view)"
            >
              <span v-if="currentView === nav.view" class="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full bg-accent" />
              <span :class="currentView === nav.view ? 'text-accent' : ''" v-html="ico(nav.icon)" />
              <span>{{ nav.label }}</span>
            </div>
          </div>

          <!-- P4：执行计划（todo_write 驱动）：侧栏可折叠面板，与会话回放同源 -->
          <div v-if="planTodos.length > 0" class="space-y-1 pt-3 border-t border-border">
            <div
              class="flex items-center justify-between px-2 text-[10px] text-stone-500 font-semibold uppercase tracking-wide cursor-pointer select-none"
              @click="planOpen = !planOpen"
            >
              <span class="flex items-center gap-1.5">
                <span class="text-stone-400 text-[9px] w-2.5 inline-block transition-transform" :class="planOpen ? 'rotate-90' : ''">▶</span>
                <span class="text-accent" v-html="ico('sparkle')" />
                <span>执行计划</span>
                <span class="font-normal text-stone-400 tabular-nums">{{ planDone }}/{{ planTodos.length }}</span>
              </span>
            </div>
            <div v-if="planOpen" class="space-y-0.5">
              <div v-for="t in planTodos" :key="t.id" class="flex items-center gap-2 px-2 py-[3px] text-[11px]">
                <span v-if="t.status === 'done'" class="text-emerald-600 shrink-0" v-html="ico('check')" />
                <span v-else-if="t.status === 'cancelled'" class="text-stone-300 shrink-0" v-html="ico('x')" />
                <span v-else-if="t.status === 'in_progress'" class="text-accent shrink-0" v-html="ico('circle')" />
                <span v-else class="text-stone-400 shrink-0" v-html="ico('circle')" />
                <span
                  class="truncate"
                  :class="t.status === 'done' || t.status === 'cancelled'
                    ? 'text-stone-400 line-through'
                    : t.status === 'in_progress' ? 'text-stone-800 font-medium' : 'text-stone-600'"
                >{{ t.content }}</span>
              </div>
            </div>
          </div>

          <!-- 代码空间（多工作区：关联目录清单 → 活动目录展开会话） -->
          <div class="space-y-1 pt-3 border-t border-border">
            <div class="flex items-center justify-between px-2 text-[10px] text-stone-500 font-semibold uppercase tracking-wide">
              <span>代码空间</span>
              <button class="hover:text-stone-700 transition-std" title="关联目录（可多选）" v-html="ico('plus')" @click="selectWorkspace" />
            </div>

            <div v-if="roots.length > 0" class="space-y-0.5">
              <div v-for="r in roots" :key="r">
                <div
                  class="group flex items-center gap-1.5 px-2 py-[7px] rounded-md hover:bg-card cursor-pointer transition-std"
                  :class="r === workspacePath ? 'text-stone-700' : 'text-stone-500'"
                  :title="r === workspacePath ? r : `${r}（点击设为活动目录）`"
                  @click="r === workspacePath ? (wsOpen = !wsOpen) : void setActiveRoot(r)"
                >
                  <span
                    v-if="r === workspacePath"
                    class="text-stone-400 text-[9px] w-2.5 inline-block transition-transform"
                    :class="wsOpen ? 'rotate-90' : ''"
                  >▶</span>
                  <span v-else class="w-2.5 inline-block" />
                  <span class="text-amber-700/80" v-html="ico('folder')" />
                  <span class="truncate font-mono text-[11px]">{{ nameOf(r) }}</span>
                  <span v-if="r === workspacePath" class="ml-auto text-[9px] text-stone-400 font-mono">{{ sessions.length }}</span>
                  <button
                    class="hidden group-hover:inline text-stone-400 hover:text-rose-600 shrink-0"
                    :class="r === workspacePath ? '' : 'ml-auto'"
                    title="移除关联目录"
                    v-html="ico('x')"
                    @click.stop="void removeRoot(r)"
                  />
                </div>

                <div v-if="r === workspacePath && wsOpen" class="pl-4 ml-3.5 space-y-0.5 tree-line">
                  <div
                    v-for="s in assistantSessions"
                    :key="s.id"
                    class="group px-2 py-[7px] rounded-md text-[11px] cursor-pointer transition-std flex items-center gap-1.5 justify-between"
                    :class="activeSessionId === s.id
                      ? 'bg-accent/10 text-accent border border-accent/25'
                      : 'text-stone-600 hover:text-stone-800 hover:bg-card border border-transparent'"
                    @click="openSession(s.id)"
                  >
                    <span class="flex items-center gap-1.5 truncate">
                      <span v-html="ico('chat')" />
                      <span class="truncate">{{ s.title }}</span>
                    </span>
                    <button
                      class="hidden group-hover:inline text-stone-400 hover:text-rose-600 shrink-0"
                      v-html="ico('x')"
                      @click.stop="deleteSession(s.id)"
                    />
                  </div>
                  <div
                    class="px-2 py-1 rounded text-[10px] text-stone-400 hover:text-stone-700 cursor-pointer flex items-center gap-1.5 transition-std"
                    @click="createSession"
                  >
                    <span v-html="ico('plus')" /> 新会话
                  </div>
                </div>
              </div>
            </div>

            <div v-else
                 class="px-2 py-2 rounded-md text-[11px] text-stone-500 hover:text-stone-700 hover:bg-card cursor-pointer flex items-center gap-1.5 transition-std"
                 @click="selectWorkspace">
              <span v-html="ico('folder')" /> 选择工作区目录
            </div>
          </div>

          <!-- P7：专家会话分组（与助理会话分开，按专家归档） -->
          <div v-if="expertSessionGroups.length > 0" class="space-y-1 pt-3 border-t border-border">
            <div class="px-2 text-[10px] text-stone-500 font-semibold uppercase tracking-wide">专家会话</div>
            <div v-for="g in expertSessionGroups" :key="g.expert.id">
              <div
                class="flex items-center gap-1.5 px-2 py-[7px] rounded-md hover:bg-card cursor-pointer transition-std text-stone-600"
                :title="g.expert.name"
                @click="expertOpen[g.expert.id] = !expertOpen[g.expert.id]"
              >
                <span class="text-stone-400 text-[9px] w-2.5 inline-block transition-transform" :class="expertOpen[g.expert.id] ? 'rotate-90' : ''">▶</span>
                <span class="w-4 h-4 rounded-md bg-surface border border-border flex items-center justify-center overflow-hidden text-[10px] shrink-0">
                  <img v-if="g.expert.logo" :src="g.expert.logo" class="w-full h-full object-cover" alt="" />
                  <span v-else>{{ g.expert.emoji }}</span>
                </span>
                <span class="truncate text-[11px]">{{ g.expert.name }}</span>
                <span class="ml-auto text-[9px] text-stone-400 font-mono">{{ g.items.length }}</span>
              </div>
              <div v-if="expertOpen[g.expert.id]" class="pl-4 ml-3.5 space-y-0.5 tree-line">
                <div
                  v-for="s in g.items"
                  :key="s.id"
                  class="group px-2 py-[7px] rounded-md text-[11px] cursor-pointer transition-std flex items-center gap-1.5 justify-between"
                  :class="activeSessionId === s.id
                    ? 'bg-accent/10 text-accent border border-accent/25'
                    : 'text-stone-600 hover:text-stone-800 hover:bg-card border border-transparent'"
                  @click="openSession(s.id)"
                >
                  <span class="flex items-center gap-1.5 truncate">
                    <span v-html="ico('chat')" />
                    <span class="truncate">{{ s.title }}</span>
                  </span>
                  <button
                    class="hidden group-hover:inline text-stone-400 hover:text-rose-600 shrink-0"
                    v-html="ico('x')"
                    @click.stop="deleteSession(s.id)"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 侧栏底部 -->
        <div class="p-2.5 border-t border-border bg-surface flex items-center justify-between">
          <div class="flex items-center gap-2">
            <div class="w-6 h-6 rounded-full bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center text-emerald-700 font-bold text-[10px]">Dev</div>
            <div class="flex flex-col">
              <span class="font-medium text-stone-700 text-[11px]">本地开发者模式</span>
              <span class="text-[9px] text-stone-500">数据存储于本机</span>
            </div>
          </div>
          <button
            class="text-stone-500 hover:text-stone-700 p-1.5 hover:bg-card rounded-md transition-std"
            title="用量统计"
            v-html="ico('chart')"
            @click="currentView = 'usage'"
          />
        </div>
      </aside>

      <!-- 中间主工作区 -->
      <main class="flex-1 flex flex-col min-w-0 bg-main relative">

        <!-- 顶部二级状态条（P2 任务 1：工作区路径 + git 分支） -->
        <div class="h-9 border-b border-border bg-surface/60 px-4 flex items-center justify-between text-[11px] text-stone-600">
          <div class="flex items-center gap-2 font-mono min-w-0">
            <span class="text-amber-700/80 shrink-0" v-html="ico('folder')" />
            <span class="text-stone-800 truncate">{{ workspacePath ?? '未选择工作区' }}</span>
            <template v-if="gitInfo">
              <span class="text-stone-300">|</span>
              <span class="flex items-center gap-1 text-stone-600 shrink-0">
                <span v-html="ico('circle')" class="text-stone-400" />
                {{ gitInfo.branch }}
                <span v-if="gitInfo.dirty > 0" class="text-amber-700">· {{ gitInfo.dirty }} 变更</span>
              </span>
            </template>
          </div>
          <div class="flex items-center gap-2">
            <span
              :class="['px-1.5 py-0.5 rounded-full text-[10px] font-medium transition-std', modeMeta(permMode).chip]"
              :title="modeMeta(permMode).d"
            >{{ permMode }}</span>
          </div>
        </div>

        <ChatView
          v-if="currentView === 'assistant' || (currentView === 'experts' && activeExpert)"
          :session-id="activeSessionId"
          :workspace-name="workspaceName"
          :workspace-roots="roots"
          :workspace-active="workspacePath"
          :expert="currentView === 'experts' ? activeExpert : null"
          @pick-workspace="selectWorkspace"
          @select-workspace-root="(p) => void setActiveRoot(p)"
          @remove-workspace-root="(p) => void removeRoot(p)"
          @workspace-changed="refreshGit"
          @rollback-done="(id) => void onRollbackDone(id)"
          @session-cleared="refreshSessions"
          @back-to-experts="() => { activeSessionId = null; }"
        />
        <ExpertsView
          v-else-if="currentView === 'experts'"
          :session-counts="sessionCounts"
          @open="(e) => void openExpert(e)"
          @changed="loadExperts"
          @removed="() => void onExpertRemoved()"
        />
        <SettingsView v-else-if="currentView === 'models'" />
        <SkillsView v-else-if="currentView === 'skills'" />
        <McpView v-else-if="currentView === 'mcp'" />
        <UsageView v-else />
      </main>
    </div>
  </div>
</template>
