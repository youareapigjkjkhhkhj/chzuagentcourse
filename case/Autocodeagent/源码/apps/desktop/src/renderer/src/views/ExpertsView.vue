<script setup lang="ts">
/**
 * P7 专家团视图（原型 v2.1 场景 G 同款）：卡片网格 + 搜索 + 创建/编辑弹窗。
 * 专家 = 人设 + 能力标签 + 绑定工具（内置 / mcp:连接器名）+ 绑定 Skills；
 * 点击卡片由外层创建/恢复绑定 expertId 的会话，复用 ChatView（不复制对话渲染）。
 * 增删改经 IPC zod 校验（§23），Logo 上传与 MCP 图标同款 data URL 流程。
 */
import { computed, onMounted, ref } from 'vue';
import type { Expert, SkillMeta } from '@agentbuddy/shared';
import { agent } from '../api/bridge';
import { useOverlayDismiss } from '../composables/useOverlayDismiss';
import { ico } from '../ui/icons';
import { bindTitle } from '../ui/expertLabel';

const props = defineProps<{
  /** 各专家的会话数（外层 sessions 聚合，卡片元信息展示） */
  sessionCounts: Record<string, number>;
}>();
const emit = defineEmits<{
  (e: 'open', expert: Expert): void;
  (e: 'changed'): void;
  (e: 'removed', id: string): void;
}>();

const experts = ref<Expert[]>([]);
const search = ref('');
const loadErr = ref('');

/** 弹窗状态：editingId 空 = 新建 */
const showModal = ref(false);
const editingId = ref('');
const formErr = ref('');
const modalBusy = ref(false);
const tagInput = ref('');

/** 遮罩点击关闭：按下与抬起都在遮罩才关，避免弹窗内拖选文本松手越界误关 */
const overlay = useOverlayDismiss(() => { showModal.value = false; });

interface ExpertForm {
  name: string;
  emoji: string;
  logo: string;
  description: string;
  persona: string;
  tags: string[];
  tools: string[];
  skills: string[];
}
const form = ref<ExpertForm>(emptyForm());
function emptyForm(): ExpertForm {
  return { name: '', emoji: '🧑‍💻', logo: '', description: '', persona: '', tags: [], tools: [], skills: [] };
}

/** 内置可绑定工具（与 agent-core createBuiltinBus 六件套对应；todo_write 始终保留不出现在清单） */
const builtinTools = [
  { id: 'read', icon: 'file', desc: '读取文件内容' },
  { id: 'grep', icon: 'search', desc: '检索代码内容' },
  { id: 'glob', icon: 'folder', desc: '按文件名找文件' },
  { id: 'edit', icon: 'pencil', desc: '编辑文件（Diff 审阅）' },
  { id: 'write', icon: 'file', desc: '写入新文件' },
  { id: 'bash', icon: 'terminal', desc: '执行命令（经 Permission Gate）' },
];
const tagPresets = ['代码审查', '单元测试', '安全审计', '重构', 'Git 提交', '性能优化', '文档撰写', '需求分析'];
const emojiPresets = ['🧑‍💻', '🧐', '🧪', '📦', '🛡️', '⚡', '🎨', '📝'];

/** 绑定选项：已连接 MCP 连接器（mcp:名称）+ 启用技能（与 / 菜单同源） */
const mcpNames = ref<string[]>([]);
const skillList = ref<SkillMeta[]>([]);
const enabledSkills = computed(() => skillList.value.filter((s) => s.enabled));

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase();
  if (!q) return experts.value;
  return experts.value.filter(
    (e) => e.name.toLowerCase().includes(q) || e.description.toLowerCase().includes(q) || e.tags.some((t) => t.toLowerCase().includes(q)),
  );
});

async function load(): Promise<void> {
  const [ex, mcp, sk] = await Promise.all([agent().expert.list(), agent().mcp.list(), agent().skills.list()]);
  if (ex.ok && ex.data) experts.value = ex.data;
  else loadErr.value = ex.error ?? '专家清单加载失败';
  if (mcp.ok && mcp.data) mcpNames.value = mcp.data.filter((v) => v.status === 'connected').map((v) => v.config.name);
  if (sk.ok && sk.data) skillList.value = sk.data;
}
onMounted(load);

function openCreate(): void {
  editingId.value = '';
  form.value = emptyForm();
  formErr.value = '';
  tagInput.value = '';
  void load(); // 绑定选项低成本刷新（连接器/技能可能刚变更）
  showModal.value = true;
}

function openEdit(e: Expert): void {
  editingId.value = e.id;
  form.value = {
    name: e.name,
    emoji: e.emoji,
    logo: e.logo ?? '',
    description: e.description,
    persona: e.persona,
    tags: [...e.tags],
    tools: [...e.tools],
    skills: [...e.skills],
  };
  formErr.value = '';
  tagInput.value = '';
  void load();
  showModal.value = true;
}

/** Logo 上传：读为 data URL，原图 ≤100KB，仅接受 image/*（MCP 图标同款） */
async function onLogoPick(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    formErr.value = 'Logo 必须为图片文件';
    return;
  }
  if (file.size > 100 * 1024) {
    formErr.value = 'Logo 过大（上限 100KB）';
    return;
  }
  form.value.logo = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error('读取失败'));
    reader.readAsDataURL(file);
  }).catch(() => '');
  if (!form.value.logo) formErr.value = 'Logo 读取失败';
}

function addTag(t: string): void {
  const tag = t.trim();
  if (!tag || tag.length > 32 || form.value.tags.includes(tag)) return;
  if (form.value.tags.length >= 8) {
    formErr.value = '能力标签最多 8 个';
    return;
  }
  form.value.tags.push(tag);
  tagInput.value = '';
}

function toggleItem(list: string[], id: string): void {
  const i = list.indexOf(id);
  if (i >= 0) list.splice(i, 1);
  else list.push(id);
}

async function save(): Promise<void> {
  const f = form.value;
  formErr.value = '';
  if (!f.name.trim()) {
    formErr.value = '请填写专家名称';
    return;
  }
  modalBusy.value = true;
  const res = await agent().expert.upsert({
    id: editingId.value || undefined,
    name: f.name.trim(),
    emoji: f.emoji || '🧑‍💻',
    logo: f.logo || undefined,
    description: f.description.trim(),
    tags: [...f.tags],
    persona: f.persona.trim(),
    tools: [...f.tools],
    skills: [...f.skills],
  });
  modalBusy.value = false;
  if (!res.ok) {
    formErr.value = res.error ?? '保存失败';
    return;
  }
  showModal.value = false;
  await load();
  emit('changed');
}

async function remove(e: Expert): Promise<void> {
  if (!window.confirm(`删除专家「${e.name}」？其历史会话保留为普通会话。`)) return;
  const res = await agent().expert.remove(e.id);
  if (!res.ok) {
    loadErr.value = res.error ?? '删除失败';
    return;
  }
  await load();
  emit('removed', e.id);
}

</script>

<template>
  <div class="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
    <!-- 头部：标题 + 搜索 + 创建 -->
    <div class="px-6 pt-5 pb-3 flex items-center gap-3">
      <div class="min-w-0">
        <h2 class="font-serif font-bold text-stone-900 text-[15px] tracking-tight flex items-center gap-2">
          <span class="text-accent" v-html="ico('users')" /> 专家团
        </h2>
        <p class="text-[11px] text-stone-500 mt-0.5">创建带人设的专家，绑定工具与 Skills 子集；点击卡片进入专属对话</p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <div class="relative">
          <span class="absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400" v-html="ico('search')" />
          <input
            v-model="search"
            class="bg-card border border-border rounded-lg pl-8 pr-3 py-1.5 text-[11px] w-44 focus:outline-none focus:border-borderLight transition-std"
            placeholder="搜索专家 / 标签…"
          />
        </div>
        <button
          class="bg-stone-800 hover:bg-stone-700 text-stone-50 px-3 py-1.5 rounded-lg text-[11px] font-medium flex items-center gap-1.5 transition-std shadow-card"
          @click="openCreate"
        >
          <span v-html="ico('plus')" /> 创建专家
        </button>
      </div>
    </div>

    <div v-if="loadErr" class="mx-6 mb-2 flex items-center justify-between bg-rose-50 border border-rose-500/30 rounded-lg px-3 py-2 text-[11px] text-rose-600">
      <span class="flex items-center gap-1.5"><span v-html="ico('alert')" /> {{ loadErr }}</span>
      <button class="text-stone-400 hover:text-stone-600" v-html="ico('x')" @click="loadErr = ''" />
    </div>

    <!-- 卡片网格 -->
    <div class="flex-1 overflow-y-auto px-6 pb-6">
      <div v-if="filtered.length === 0" class="h-full flex flex-col items-center justify-center text-stone-400 gap-2 py-16">
        <span class="text-stone-300" v-html="ico('users')" />
        <p class="text-[12px]">{{ experts.length === 0 ? '还没有专家，点击右上角「创建专家」组建你的专家团' : '没有匹配的专家' }}</p>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3.5">
        <div
          v-for="e in filtered"
          :key="e.id"
          class="bg-card border border-border rounded-xl p-4 space-y-2.5 shadow-card hover:border-borderLight hover:shadow-popover transition-std cursor-pointer flex flex-col"
          @click="emit('open', e)"
        >
          <!-- 头像 + 名称 + 标签 -->
          <div class="flex items-start gap-2.5">
            <span class="w-10 h-10 rounded-xl bg-surface border border-border flex items-center justify-center overflow-hidden shrink-0 text-[20px]">
              <img v-if="e.logo" :src="e.logo" class="w-full h-full object-cover" alt="" />
              <span v-else>{{ e.emoji }}</span>
            </span>
            <div class="min-w-0 flex-1">
              <div class="font-semibold text-stone-900 text-[12.5px] truncate">{{ e.name }}</div>
              <div class="flex flex-wrap gap-1 mt-1">
                <span
                  v-for="t in e.tags.slice(0, 3)"
                  :key="t"
                  class="px-1.5 py-px rounded-full bg-accent/10 text-accent border border-accent/25 text-[9.5px] font-medium"
                >{{ t }}</span>
                <span v-if="e.tags.length > 3" class="px-1.5 py-px rounded-full bg-surface border border-border text-stone-400 text-[9.5px]">+{{ e.tags.length - 3 }}</span>
              </div>
            </div>
          </div>

          <p class="text-[11px] text-stone-500 leading-relaxed line-clamp-2 min-h-[30px]">{{ e.description || '这位专家很低调，没有填写简介' }}</p>

          <!-- 绑定摘要：工具 / 技能 计数 + 小图标（hover 看全量清单）；计数式避免长清单撑高卡片 -->
          <div class="flex items-center gap-1.5" :title="bindTitle(e)">
            <span v-if="e.tools.length > 0" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-700 border border-blue-500/25 text-[10px] font-medium">
              <span v-html="ico('wrench')" /> 工具 {{ e.tools.length }} 个
            </span>
            <span v-if="e.skills.length > 0" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-700 border border-indigo-500/25 text-[10px] font-medium">
              <span v-html="ico('sparkle')" /> 技能 {{ e.skills.length }} 个
            </span>
            <span v-if="e.tools.length === 0 && e.skills.length === 0" class="text-[10px] text-stone-400">未绑定（全量工具与技能可用）</span>
          </div>

          <!-- 底部：会话数 + 操作 -->
          <div class="flex items-center justify-between pt-1.5 border-t border-border/70 mt-auto">
            <span class="text-[10px] text-stone-400 flex items-center gap-1">
              <span v-html="ico('chat')" /> {{ props.sessionCounts[e.id] ?? 0 }} 个会话
            </span>
            <div class="flex items-center gap-1">
              <button
                class="px-2 py-1 rounded-md bg-stone-800 text-stone-50 text-[10.5px] font-medium hover:bg-stone-700 transition-std"
                @click.stop="emit('open', e)"
              >对话</button>
              <button
                class="p-1 rounded-md text-stone-400 hover:text-stone-700 hover:bg-surface transition-std"
                title="编辑专家"
                v-html="ico('pencil')"
                @click.stop="openEdit(e)"
              />
              <button
                class="p-1 rounded-md text-stone-400 hover:text-rose-600 hover:bg-surface transition-std"
                title="删除专家"
                v-html="ico('trash')"
                @click.stop="void remove(e)"
              />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ 弹窗：创建 / 编辑专家 ═══ -->
    <div
      v-if="showModal"
      class="fixed inset-0 z-50 flex items-center justify-center modal-overlay"
      @mousedown="overlay.onOverlayDown"
      @click="overlay.onOverlayClick"
    >
      <div class="bg-card border border-border rounded-2xl shadow-popover w-full max-w-2xl mx-4 overflow-hidden max-h-[85vh] flex flex-col" @click.stop>
        <div class="flex items-center justify-between px-6 py-4 border-b border-border">
          <h3 class="font-bold text-stone-900 flex items-center gap-2">
            <span class="text-accent" v-html="ico('users')" />
            {{ editingId ? `编辑专家 ${form.name || ''}` : '创建专家' }}
          </h3>
          <button class="text-stone-500 hover:text-stone-700 p-1" v-html="ico('x')" @click="showModal = false" />
        </div>

        <div class="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          <!-- Logo / Emoji + 名称 -->
          <div class="flex items-start gap-4">
            <div class="space-y-1.5">
              <span class="w-14 h-14 rounded-2xl bg-surface border border-border flex items-center justify-center overflow-hidden text-[28px]">
                <img v-if="form.logo" :src="form.logo" class="w-full h-full object-cover" alt="logo" />
                <span v-else>{{ form.emoji }}</span>
              </span>
              <div class="flex gap-1.5">
                <label class="flex items-center gap-1 bg-surface hover:bg-cardHover border border-border rounded-md px-1.5 py-1 text-[9.5px] text-stone-600 transition-std cursor-pointer">
                  <span v-html="ico('upload')" /> 上传 Logo
                  <input type="file" accept="image/*" class="hidden" @change="(e) => void onLogoPick(e)" />
                </label>
                <button v-if="form.logo" class="text-[9.5px] text-stone-400 hover:text-rose-600 transition-std" @click="form.logo = ''">移除</button>
              </div>
            </div>
            <div class="flex-1 space-y-2.5">
              <div>
                <label class="block text-[11px] text-stone-600 mb-1">名称 <span class="text-rose-500">*</span></label>
                <input
                  v-model="form.name"
                  class="w-full bg-surface border border-border rounded-lg px-3 py-1.5 text-[12px] focus:outline-none focus:border-borderLight transition-std"
                  placeholder="如：代码审查专家"
                  maxlength="64"
                />
              </div>
              <div>
                <label class="block text-[11px] text-stone-600 mb-1">头像 Emoji <span class="text-stone-400">(未上传 Logo 时展示)</span></label>
                <div class="flex gap-1.5">
                  <button
                    v-for="em in emojiPresets"
                    :key="em"
                    class="w-7 h-7 rounded-lg border text-[15px] transition-std"
                    :class="form.emoji === em && !form.logo ? 'border-accent bg-accent/10' : 'border-border bg-surface hover:border-borderLight'"
                    @click="form.emoji = em; form.logo = ''"
                  >{{ em }}</button>
                </div>
              </div>
            </div>
          </div>

          <div>
            <label class="block text-[11px] text-stone-600 mb-1">简介</label>
            <textarea
              v-model="form.description"
              rows="2"
              class="w-full bg-surface border border-border rounded-lg px-3 py-1.5 text-[11.5px] focus:outline-none focus:border-borderLight transition-std resize-none"
              placeholder="一句话说明这位专家擅长什么（卡片展示）"
              maxlength="300"
            />
          </div>

          <!-- 能力标签 -->
          <div>
            <label class="block text-[11px] text-stone-600 mb-1">能力标签 <span class="text-stone-400">(回车添加，最多 8 个)</span></label>
            <div class="flex flex-wrap gap-1.5 mb-1.5">
              <span
                v-for="t in form.tags"
                :key="t"
                class="px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/25 text-[10px] font-medium flex items-center gap-1"
              >
                {{ t }}
                <button class="hover:text-rose-600" v-html="ico('x')" @click="form.tags = form.tags.filter((x) => x !== t)" />
              </span>
            </div>
            <input
              v-model="tagInput"
              class="w-full bg-surface border border-border rounded-lg px-3 py-1.5 text-[11px] focus:outline-none focus:border-borderLight transition-std"
              placeholder="输入标签后回车，如：安全审计"
              @keydown.enter.prevent="addTag(tagInput)"
            />
            <div class="flex flex-wrap gap-1 mt-1.5">
              <button
                v-for="p in tagPresets.filter((x) => !form.tags.includes(x))"
                :key="p"
                class="px-1.5 py-px rounded-full bg-surface border border-border text-stone-500 text-[9.5px] hover:border-borderLight hover:text-stone-700 transition-std"
                @click="addTag(p)"
              >+ {{ p }}</button>
            </div>
          </div>

          <!-- 人设 -->
          <div>
            <label class="block text-[11px] text-stone-600 mb-1">人设 / System Prompt <span class="text-stone-400">(追加到系统提示，空 = 不注入)</span></label>
            <textarea
              v-model="form.persona"
              rows="4"
              class="w-full bg-surface border border-border rounded-lg px-3 py-2 text-[11px] font-mono focus:outline-none focus:border-borderLight transition-std resize-none"
              placeholder="如：你是资深代码审查专家，只读分析工作区代码，按正确性/安全/可读性/测试四维度输出结构化报告…"
            />
          </div>

          <!-- 绑定工具 -->
          <div>
            <label class="block text-[11px] text-stone-600 mb-1">绑定工具 <span class="text-stone-400">(不选 = 全量可用；写/执行仍经权限矩阵)</span></label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="t in builtinTools"
                :key="t.id"
                class="px-2 py-1 rounded-lg border text-[10.5px] font-mono transition-std"
                :class="form.tools.includes(t.id) ? 'bg-blue-500/15 border-blue-500/40 text-blue-700' : 'bg-surface border-border text-stone-500 hover:border-borderLight'"
                :title="t.desc"
                @click="toggleItem(form.tools, t.id)"
              >{{ t.id }}</button>
              <button
                v-for="n in mcpNames"
                :key="n"
                class="px-2 py-1 rounded-lg border text-[10.5px] font-mono transition-std"
                :class="form.tools.includes(`mcp:${n}`) ? 'bg-purple-500/15 border-purple-500/40 text-purple-700' : 'bg-surface border-border text-stone-500 hover:border-borderLight'"
                :title="`绑定连接器 #${n} 的全部工具`"
                @click="toggleItem(form.tools, `mcp:${n}`)"
              >#{{ n }}</button>
              <span v-if="mcpNames.length === 0" class="text-[10px] text-stone-400 self-center">（无已连接 MCP 连接器）</span>
            </div>
          </div>

          <!-- 绑定 Skills -->
          <div>
            <label class="block text-[11px] text-stone-600 mb-1">绑定 Skills <span class="text-stone-400">(不选 = 全部启用技能；选中后 / 菜单只列这些)</span></label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="s in enabledSkills"
                :key="`${s.source}:${s.name}`"
                class="px-2 py-1 rounded-lg border text-[10.5px] font-mono transition-std"
                :class="form.skills.includes(s.name) ? 'bg-indigo-500/15 border-indigo-500/40 text-indigo-700' : 'bg-surface border-border text-stone-500 hover:border-borderLight'"
                :title="`${s.description}（${s.source === 'project' ? '项目级' : '全局'}）`"
                @click="toggleItem(form.skills, s.name)"
              >/{{ s.name }}</button>
              <span v-if="enabledSkills.length === 0" class="text-[10px] text-stone-400 self-center">（暂无启用技能，可在「技能 Skills」页创建）</span>
            </div>
          </div>

          <div v-if="formErr" class="flex items-center gap-1.5 bg-rose-50 border border-rose-500/30 rounded-lg px-3 py-2 text-[11px] text-rose-600">
            <span v-html="ico('alert')" /> {{ formErr }}
          </div>
        </div>

        <div class="flex items-center justify-end gap-2 px-6 py-4 border-t border-border">
          <button class="px-3 py-1.5 rounded-lg border border-border text-stone-600 text-[11px] hover:bg-surface transition-std" @click="showModal = false">取消</button>
          <button
            class="px-4 py-1.5 rounded-lg bg-stone-800 hover:bg-stone-700 text-stone-50 text-[11px] font-medium transition-std disabled:opacity-50"
            :disabled="modalBusy"
            @click="void save()"
          >{{ modalBusy ? '保存中…' : editingId ? '保存修改' : '创建专家' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
