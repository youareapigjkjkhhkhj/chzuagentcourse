<script setup lang="ts">
/**
 * P4 Skills 管理页：卡片式清单（名称 / 描述 / 来源徽标 / 状态开关 / 触发方式 / 查看编辑）。
 * 全局 ~/.AgentBuddy/skills + 项目 <ws>/.AgentBuddy/skills 两级，同名项目覆盖全局；
 * 畸形 SKILL.md 显示告警（不阻塞启动）；启停持久化后立即反映到下一次上下文组装。
 */
import { computed, onMounted, ref } from 'vue';
import type { SkillMeta } from '@agentbuddy/shared';
import { agent } from '../api/bridge';
import { useOverlayDismiss } from '../composables/useOverlayDismiss';
import { ico } from '../ui/icons';

const skills = ref<SkillMeta[]>([]);
const err = ref('');
const editing = ref<SkillMeta | null>(null);
const editRaw = ref('');
const saving = ref(false);

/** 新增弹窗（原型同款表单：名称 + 来源 + 描述 + 正文） */
const creating = ref(false);
const form = ref({ name: '', scope: 'global' as 'global' | 'project', description: '', body: '' });
const formErr = ref('');
const creatingBusy = ref(false);
const hasWorkspace = ref(false);
const notice = ref('');
const importing = ref(false);

/** 遮罩点击关闭（两个弹窗各自一份）：按下与抬起都在遮罩才关，避免拖选正文复制时松手越界误关 */
const editOverlay = useOverlayDismiss(() => { editing.value = null; });
const createOverlay = useOverlayDismiss(() => { creating.value = false; });

const warnings = computed(() => skills.value.filter((s) => s.warning));

async function load(): Promise<void> {
  const res = await agent().skills.list();
  if (res.ok && res.data) skills.value = res.data;
  else err.value = res.error ?? '加载技能失败';
}

function openCreate(): void {
  form.value = { name: '', scope: hasWorkspace.value ? 'project' : 'global', description: '', body: '' };
  formErr.value = '';
  creating.value = true;
}

/** 新增：Main 端 zod + slug 校验 + 同范围查重，写入 <name>/SKILL.md（含 frontmatter） */
async function submitCreate(): Promise<void> {
  const f = form.value;
  if (!f.name.trim() || !f.description.trim()) {
    formErr.value = '名称与描述为必填项';
    return;
  }
  creatingBusy.value = true;
  const res = await agent().skills.create({ name: f.name.trim(), scope: f.scope, description: f.description.trim(), body: f.body });
  creatingBusy.value = false;
  if (res.ok) {
    creating.value = false;
    await load();
  } else {
    formErr.value = res.error ?? '创建失败';
  }
}

/** 删除：二次确认后移除 <name> 目录（仅两级 skills 根内） */
async function removeSkill(s: SkillMeta): Promise<void> {
  const scopeLabel = s.source === 'project' ? '项目' : '全局';
  if (!window.confirm(`确定删除技能 /${s.name}（${scopeLabel}）吗？目录将被移除，不可恢复。`)) return;
  const res = await agent().skills.remove(s.name);
  if (!res.ok) err.value = res.error ?? '删除失败';
  await load();
}

/** ArrayBuffer → base64（分块避免字符串拼接栈溢出） */
function bufToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

/** 导入 ZIP 技能包：读文件 → base64 走 IPC → Main 解包校验落盘（默认入全局） */
async function onZipPick(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    err.value = 'ZIP 过大（上限 10MB）';
    return;
  }
  importing.value = true;
  err.value = '';
  notice.value = '';
  try {
    const res = await agent().skills.importZip(bufToBase64(await file.arrayBuffer()), 'global');
    if (res.ok && res.data) {
      notice.value = `已导入 ${res.data.length} 个技能：${res.data.map((m) => '/' + m.name).join('、')}`;
      await load();
    } else {
      err.value = res.error ?? '导入失败';
    }
  } finally {
    importing.value = false;
  }
}

/** 启停：持久化 disabledSkills，下一次上下文组装生效（§18 事件驱动，无轮询） */
async function toggle(s: SkillMeta): Promise<void> {
  if (s.warning) return;
  const res = await agent().skills.setEnabled(s.name, !s.enabled);
  if (!res.ok) err.value = res.error ?? '操作失败';
  await load();
}

async function openEdit(s: SkillMeta): Promise<void> {
  const res = await agent().skills.get(s.name);
  if (res.ok && res.data) {
    editing.value = s;
    editRaw.value = res.data.raw;
  } else {
    err.value = res.error ?? '读取技能失败';
  }
}

/** 保存整个 SKILL.md（含 frontmatter）；畸形时管理页以告警形式提示 */
async function saveEdit(): Promise<void> {
  if (!editing.value) return;
  saving.value = true;
  const res = await agent().skills.save(editing.value.name, editRaw.value);
  saving.value = false;
  if (res.ok) {
    editing.value = null;
    await load();
  } else {
    err.value = res.error ?? '保存失败';
  }
}

function insertToComposer(s: SkillMeta): void {
  void navigator.clipboard.writeText(`/${s.name} `).catch(() => undefined);
}

onMounted(() => {
  void load();
  void agent().workspace.get().then((res) => {
    hasWorkspace.value = res.ok && !!res.data;
  });
});
</script>

<template>
  <div class="flex-1 overflow-y-auto p-6 space-y-4 w-full">
    <div class="space-y-1">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-serif font-bold text-stone-900 flex items-center gap-2">
          <span class="text-accent" v-html="ico('sparkle')" /> 技能 Skills
        </h2>
        <div class="flex items-center gap-2">
          <label
            class="flex items-center gap-1.5 bg-emerald-500/10 border border-emerald-500/25 hover:bg-emerald-500/20 text-emerald-700 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-std cursor-pointer"
            :class="importing ? 'opacity-50 pointer-events-none' : ''"
            title="选择含 &lt;name&gt;/SKILL.md 的 zip（references/scripts 等附属文件一并导入），入全局目录"
          >
            <span v-html="ico('upload')" /> {{ importing ? '导入中…' : '导入 ZIP 技能包' }}
            <input type="file" accept=".zip" class="hidden" @change="void onZipPick($event)" />
          </label>
          <button
            class="flex items-center gap-1.5 bg-accent hover:bg-accentDim text-white px-3 py-1.5 rounded-lg text-[11px] font-medium transition-std shadow-sm"
            @click="openCreate"
          >
            <span v-html="ico('plus')" /> 新增技能
          </button>
        </div>
      </div>
      <p class="text-[11px] text-stone-500 leading-relaxed max-w-4xl">
        技能 = Markdown 指令资产（纯文本，不含可执行脚本）。两级目录：全局
        <span class="font-mono text-[10px] bg-surface px-1 rounded border border-border">~/.AgentBuddy/skills/</span>
        与项目级
        <span class="font-mono text-[10px] bg-surface px-1 rounded border border-border">&lt;工作区&gt;/.AgentBuddy/skills/</span>，
        同名时项目覆盖全局。启用技能的摘要进系统提示目录，模型需要时用 read 自取正文；输入框键入
        <span class="font-mono text-[10px] bg-surface px-1 rounded border border-border">/</span> 可触发。
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

    <!-- 畸形告警：不阻塞，仅提示（验收条件） -->
    <div v-if="warnings.length > 0" class="bg-amber-50 border border-amber-500/30 rounded-lg px-3 py-2 space-y-1">
      <div v-for="w in warnings" :key="w.path" class="flex items-start gap-1.5 text-[11px] text-amber-700">
        <span class="shrink-0 mt-px" v-html="ico('alert')" />
        <span><span class="font-mono">{{ w.name }}/SKILL.md</span>：{{ w.warning }}（已跳过，不参与注入与触发）</span>
      </div>
    </div>

    <!-- 技能卡片 -->
    <div v-if="skills.length === 0" class="text-center text-stone-400 text-[11px] py-10">
      暂无技能。点击右上角「新增技能」，或在目录内放置 <span class="font-mono">&lt;name&gt;/SKILL.md</span>（frontmatter 含 name / description）即可被识别。
    </div>
    <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
      <div
        v-for="s in skills"
        :key="s.path"
        :class="['bg-card border rounded-xl p-3.5 space-y-2.5 shadow-card transition-std', s.enabled ? 'border-border' : 'border-border opacity-60']"
      >
        <div class="flex items-center gap-2">
          <span class="font-mono text-[12px] font-semibold text-stone-900">/{{ s.name }}</span>
          <span
            :class="['px-1.5 py-0.5 rounded-full text-[9.5px] font-medium',
              s.source === 'project' ? 'bg-accent/10 text-accent border border-accent/25' : 'bg-surface text-stone-500 border border-border']"
          >{{ s.source === 'project' ? '项目' : '全局' }}</span>
          <span v-if="s.warning" class="px-1.5 py-0.5 rounded-full text-[9.5px] font-medium bg-amber-500/10 text-amber-700 border border-amber-500/25">畸形</span>

          <!-- 启用开关 -->
          <button
            v-if="!s.warning"
            class="ml-auto shrink-0 w-8 h-4.5 rounded-full transition-std relative"
            :class="s.enabled ? 'bg-accent/70' : 'bg-stone-300'"
            :title="s.enabled ? '点击禁用' : '点击启用'"
            @click="void toggle(s)"
          >
            <span
              class="absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white shadow-sm transition-std"
              :class="s.enabled ? 'left-4' : 'left-0.5'"
            />
          </button>
        </div>

        <p class="text-[11px] text-stone-600 leading-relaxed line-clamp-2" :title="s.description || s.warning || ''">{{ s.description || s.warning || '（无描述）' }}</p>

        <div class="flex items-center gap-2 text-[10px] text-stone-400">
          <span class="font-mono truncate max-w-[220px]" :title="s.path">{{ s.path }}</span>
        </div>

        <div class="flex items-center gap-2 pt-1 border-t border-border min-w-0">
          <span class="text-[10px] text-stone-400 truncate min-w-0" :title="`触发：输入框键入 /${s.name}`">触发：输入框键入 <span class="font-mono text-stone-600">/{{ s.name }}</span></span>
          <div class="ml-auto flex items-center gap-1 shrink-0">
            <button
              class="px-2 py-1 rounded-md text-[10.5px] text-stone-600 hover:bg-surface transition-std flex items-center gap-1 whitespace-nowrap"
              title="复制触发命令"
              @click="insertToComposer(s)"
            >
              <span v-html="ico('copy')" /> 复制
            </button>
            <button
              class="px-2 py-1 rounded-md text-[10.5px] text-stone-600 hover:bg-surface transition-std flex items-center gap-1 whitespace-nowrap"
              title="查看 / 编辑 SKILL.md"
              @click="void openEdit(s)"
            >
              <span v-html="ico('pencil')" /> 查看 / 编辑
            </button>
            <button
              class="p-1.5 rounded-md text-stone-400 hover:text-rose-600 hover:bg-rose-500/10 transition-std"
              title="删除技能"
              @click="void removeSkill(s)"
            >
              <span v-html="ico('trash')" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 编辑弹层：全文（含 frontmatter）保存 -->
    <div
      v-if="editing"
      class="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-6"
      @mousedown="editOverlay.onOverlayDown"
      @click="editOverlay.onOverlayClick"
    >
      <div class="bg-card border border-border rounded-2xl shadow-popover w-full max-w-2xl max-h-[80vh] flex flex-col">
        <div class="flex items-center justify-between px-4 py-3 border-b border-border">
          <span class="font-mono text-[12px] font-semibold text-stone-900">/{{ editing.name }}/SKILL.md</span>
          <button class="text-stone-400 hover:text-stone-600" v-html="ico('x')" @click="editing = null" />
        </div>
        <textarea
          v-model="editRaw"
          class="flex-1 min-h-[300px] bg-transparent p-4 font-mono text-[11px] leading-relaxed text-stone-700 outline-none resize-none select-text"
          spellcheck="false"
        />
        <div class="flex items-center justify-between px-4 py-3 border-t border-border">
          <span class="text-[10px] text-stone-400">frontmatter 需含 name / description；保存后立即生效</span>
          <div class="flex items-center gap-2">
            <button
              class="px-3 py-1.5 rounded-lg text-[11px] text-stone-600 hover:bg-surface transition-std"
              @click="editing = null"
            >取消</button>
            <button
              class="px-3 py-1.5 rounded-lg text-[11px] bg-accent hover:bg-accentDim text-white transition-std disabled:opacity-50"
              :disabled="saving"
              @click="void saveEdit()"
            >{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 新增弹窗：原型同款表单（名称 + 来源 + 描述 + 正文） -->
    <div
      v-if="creating"
      class="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-6"
      @mousedown="createOverlay.onOverlayDown"
      @click="createOverlay.onOverlayClick"
    >
      <div class="bg-card border border-border rounded-2xl shadow-popover w-full max-w-2xl max-h-[80vh] flex flex-col">
        <div class="flex items-center justify-between px-4 py-3 border-b border-border">
          <span class="font-serif text-[13px] font-bold text-stone-900 flex items-center gap-2">
            <span class="text-accent" v-html="ico('sparkle')" /> 新增技能
          </span>
          <button class="text-stone-400 hover:text-stone-600" v-html="ico('x')" @click="creating = false" />
        </div>

        <div class="p-5 space-y-4 overflow-y-auto">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-[11px] text-stone-600 mb-1.5">技能名称 <span class="text-rose-600">*</span></label>
              <input
                v-model="form.name"
                placeholder="review / test / commit（字母/数字/_/-）"
                class="w-full bg-surface border border-border focus:border-accent/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 placeholder-stone-400 font-mono transition-std"
                spellcheck="false"
              />
            </div>
            <div>
              <label class="block text-[11px] text-stone-600 mb-1.5">来源 <span class="text-stone-400">(同名时项目级覆盖全局)</span></label>
              <select
                v-model="form.scope"
                class="w-full bg-surface border border-border focus:border-accent/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 transition-std"
              >
                <option value="global">全局 (~/.AgentBuddy/skills/)</option>
                <option value="project" :disabled="!hasWorkspace">当前项目 (&lt;工作区&gt;/.AgentBuddy/skills/)</option>
              </select>
            </div>
          </div>

          <div>
            <label class="block text-[11px] text-stone-600 mb-1.5">描述 <span class="text-stone-400">(注入系统提示目录，模型据此决定何时使用)</span></label>
            <textarea
              v-model="form.description"
              rows="2"
              placeholder="该技能的用途与触发场景…"
              class="w-full bg-surface border border-border focus:border-accent/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 placeholder-stone-400 resize-none transition-std"
            />
          </div>

          <div>
            <label class="block text-[11px] text-stone-600 mb-1.5">SKILL.md 正文 <span class="text-stone-400">(Markdown 指令，不执行脚本；触发时作为高优先级指令注入)</span></label>
            <textarea
              v-model="form.body"
              rows="8"
              placeholder="# 技能指令&#10;&#10;1. …&#10;2. …"
              class="w-full bg-surface border border-border focus:border-accent/50 rounded-lg px-3 py-2 text-xs outline-none text-stone-800 placeholder-stone-400 resize-none font-mono leading-relaxed transition-std"
              spellcheck="false"
            />
          </div>

          <div v-if="formErr" class="flex items-center gap-1.5 bg-rose-50 border border-rose-500/30 rounded-lg px-3 py-2 text-[11px] text-rose-600">
            <span v-html="ico('alert')" /> {{ formErr }}
          </div>
        </div>

        <div class="flex items-center justify-end gap-3 px-5 py-3.5 border-t border-border bg-surface">
          <button class="px-4 py-2 text-stone-600 hover:text-stone-800 text-[11px] font-medium transition-std" @click="creating = false">取消</button>
          <button
            class="px-5 py-2 bg-accent hover:bg-accentDim text-white rounded-lg text-[11px] font-medium shadow-sm transition-std disabled:opacity-50"
            :disabled="creatingBusy"
            @click="void submitCreate()"
          >{{ creatingBusy ? '创建中…' : '创建技能' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
