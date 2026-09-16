<script setup lang="ts">
/** 模型配置中心：紧凑卡片列表 + 新增/编辑弹框。
 * 高级参数（温度 / Max Tokens / 上下文窗口）不在 UI 暴露，对齐 Claude Code 等主流 Agent，
 * 省略时由 Main 端补默认值。 */
import { computed, onMounted, reactive, ref } from 'vue';
import { maskKey, type ModelConfig, type ModelConfigInput, type WebConfigView } from '@agentbuddy/shared';
import { agent } from '../api/bridge';
import { useOverlayDismiss } from '../composables/useOverlayDismiss';
import { ico } from '../ui/icons';

/** 厂商（素材/img 内有 logo 的全部厂商）：下拉选择，预置 Base URL 与默认模型 */
const PROVIDER_PRESET: Record<string, { logo: string; baseUrl: string; model: string; hint: string }> = {
  openai: { logo: 'img/openai.png', baseUrl: 'https://api.openai.com/v1', model: 'gpt-5-mini', hint: 'OpenAI 官方 / 中转网关' },
  deepseek: { logo: 'img/deepseek-color.png', baseUrl: 'https://api.deepseek.com/v1', model: 'deepseek-chat', hint: 'DeepSeek 开放平台' },
  qwen: { logo: 'img/qwen-color.png', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus', hint: '阿里云百炼（DashScope）' },
  zhipu: { logo: 'img/zhipu-color.png', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-plus', hint: '智谱 AI 开放平台' },
  ollama: { logo: 'img/ollama.png', baseUrl: 'http://localhost:11434/v1', model: 'qwen2.5-coder:7b', hint: '本地 Ollama 服务' },
  vllm: { logo: 'img/vllm-color.png', baseUrl: 'http://localhost:8000/v1', model: 'Qwen/Qwen2.5-Coder-7B', hint: '本地 vLLM 服务' },
};
const PROVIDERS = Object.keys(PROVIDER_PRESET);

const logoOf = (provider: string): string | undefined => PROVIDER_PRESET[provider.toLowerCase()]?.logo;

const models = ref<ModelConfig[]>([]);
const activeId = ref('');
const editingId = ref<string | null>(null); // null = 未编辑；'' = 新建
const saved = ref(false);
const error = ref('');

const form = reactive<ModelConfigInput & { id?: string }>({
  name: '默认模型',
  provider: 'openai',
  baseUrl: 'https://api.openai.com/v1',
  model: 'gpt-4o-mini',
  apiKey: '',
  encrypted: false,
});

const editing = computed(() => editingId.value !== null);
const editingModel = computed(() => models.value.find((m) => m.id === editingId.value) ?? null);
/** P6：Renderer 仅见掩码 —— 输入了新 Key 显示新掩码；编辑留空显示当前掩码（= 保留原 Key） */
const keyHint = computed(() => {
  if (form.apiKey) return `新 Key：${maskKey(form.apiKey)}`;
  if (editingModel.value?.apiKeyMask) return `当前 ${editingModel.value.apiKeyMask} · 留空保留`;
  return '未设置';
});

async function reload(): Promise<void> {
  const list = await agent().config.listModels();
  if (list.ok && list.data) models.value = list.data;
  const active = await agent().config.getModel();
  if (active.ok && active.data) activeId.value = active.data.id;
}

onMounted(() => { void reload(); void loadWeb(); });

function startCreate(): void {
  editingId.value = '';
  error.value = '';
  Object.assign(form, {
    id: undefined, name: '新模型', provider: 'openai',
    baseUrl: PROVIDER_PRESET['openai']!.baseUrl, model: PROVIDER_PRESET['openai']!.model,
    apiKey: '', encrypted: false,
  });
}

/** 下拉切换厂商：预置 Base URL 与默认模型，logo 自动匹配 */
function onProviderChange(provider: string): void {
  form.provider = provider;
  const preset = PROVIDER_PRESET[provider];
  if (preset) {
    form.baseUrl = preset.baseUrl;
    form.model = preset.model;
  }
}

function startEdit(m: ModelConfig): void {
  editingId.value = m.id;
  error.value = '';
  // P6：Renderer 拿不到明文，apiKey 恒为空串；留空提交 = 保留原 Key（Main 侧处理）
  Object.assign(form, { id: m.id, name: m.name, provider: m.provider, baseUrl: m.baseUrl, model: m.model, apiKey: '', encrypted: false });
}

function cancelEdit(): void {
  editingId.value = null;
  error.value = '';
}

/** 遮罩点击关闭：按下与抬起都在遮罩才关，避免弹框内拖选文本（复制 Key / URL）松手越界误关 */
const overlay = useOverlayDismiss(cancelEdit);

async function save(): Promise<void> {
  saved.value = false;
  error.value = '';
  const res = await agent().config.setModel({ ...form, id: editingId.value || undefined });
  if (!res.ok) {
    error.value = res.error ?? '保存失败';
    return;
  }
  saved.value = true;
  setTimeout(() => {
    saved.value = false;
    editingId.value = null;
  }, 600);
  await reload();
}

async function setActive(id: string): Promise<void> {
  error.value = '';
  const res = await agent().config.setActive(id);
  if (res.ok) activeId.value = id;
  else error.value = res.error ?? '切换失败';
}

async function removeModel(m: ModelConfig): Promise<void> {
  error.value = '';
  const res = await agent().config.removeModel(m.id);
  if (!res.ok) error.value = res.error ?? '删除失败';
  else await reload();
}

/* ── 联网搜索配置（webfetch 内置零配置；websearch 需开启 + Tavily key，加密存 KeyStore） ── */
const web = reactive<WebConfigView>({ enabled: false, provider: 'tavily', hasKey: false, keyMask: undefined });
const webKey = ref('');
const webSaved = ref(false);
const webError = ref('');

/** Renderer 仅见掩码：输入新 Key 显示新掩码；留空且有存量显示当前掩码（= 保留） */
const webKeyHint = computed(() => {
  if (webKey.value) return `新 Key：${maskKey(webKey.value)}`;
  if (web.hasKey && web.keyMask) return `当前 ${web.keyMask} · 留空保留`;
  return '未设置';
});

async function loadWeb(): Promise<void> {
  const res = await agent().config.getWeb();
  if (res.ok && res.data) Object.assign(web, res.data);
}

async function saveWeb(): Promise<void> {
  webSaved.value = false;
  webError.value = '';
  const res = await agent().config.setWeb({
    enabled: web.enabled,
    provider: web.provider,
    ...(webKey.value ? { plainKey: webKey.value } : {}),
  });
  if (!res.ok) { webError.value = res.error ?? '保存失败'; return; }
  if (res.data) Object.assign(web, res.data);
  webKey.value = '';
  webSaved.value = true;
  setTimeout(() => { webSaved.value = false; }, 1200);
}

async function clearWebKey(): Promise<void> {
  webError.value = '';
  const res = await agent().config.setWeb({ plainKey: '' });
  if (!res.ok) { webError.value = res.error ?? '清除失败'; return; }
  if (res.data) Object.assign(web, res.data);
  webKey.value = '';
}
</script>

<template>
  <div class="flex-1 flex flex-col overflow-hidden">
    <div class="h-12 border-b border-border bg-surface/50 px-4 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <span class="text-blue-700" v-html="ico('cpu')" />
        <div>
          <h2 class="font-bold text-stone-900 text-sm">模型配置中心</h2>
          <p class="text-[10px] text-stone-500">OpenAI 兼容接口 · 支持多模型配置，对话框可切换 · API Key 仅本机存储</p>
        </div>
      </div>
      <button
        class="flex items-center gap-1.5 bg-accent hover:bg-accentDim text-white px-3 py-1.5 rounded-lg text-[11px] font-medium transition-std shadow-sm"
        @click="startCreate"
      >
        <span v-html="ico('plus')" /> 新增模型
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-6 space-y-4">
      <div v-if="error" class="flex items-center gap-1.5 bg-rose-50 border border-rose-500/30 rounded-lg px-3 py-2 text-[11px] text-rose-600">
        <span v-html="ico('alert')" /> {{ error }}
      </div>

      <!-- 配置卡片列表（紧凑小卡） -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
        <div
          v-for="m in models"
          :key="m.id"
          :class="['bg-card rounded-xl p-3.5 shadow-card transition-std border', m.id === activeId ? 'border-accent/50 shadow-glow' : 'border-border hover:border-borderLight']"
        >
          <div class="flex items-center gap-2.5 mb-2">
            <div class="w-9 h-9 rounded-lg bg-surface border border-border flex items-center justify-center overflow-hidden shrink-0">
              <img v-if="logoOf(m.provider)" :src="logoOf(m.provider)" class="w-6 h-6 object-contain" alt="" />
              <span v-else class="text-stone-500" v-html="ico('cpu')" />
            </div>
            <div class="min-w-0">
              <div class="font-semibold text-stone-800 text-[12px] truncate">{{ m.name }}</div>
              <div class="text-[10px] text-stone-500 font-mono truncate">{{ m.provider }} · {{ m.model }}</div>
            </div>
            <span
              v-if="m.id === activeId"
              class="ml-auto shrink-0 text-[9px] px-1.5 py-0.5 rounded-full font-medium bg-emerald-500/10 text-emerald-700 border border-emerald-500/25"
            >使用中</span>
          </div>

          <div class="flex items-center justify-between text-[10px] text-stone-500 font-mono bg-surface border border-border rounded-lg px-2.5 py-1.5 mb-2.5">
            <span class="truncate">{{ m.apiKeyMask ?? 'Key 未设置' }}</span>
            <span class="text-emerald-700 flex items-center gap-1 shrink-0"><span v-html="ico('shield')" /></span>
          </div>

          <div class="flex items-center gap-1.5">
            <button
              v-if="m.id !== activeId"
              class="flex-1 px-2 py-1.5 rounded-lg border border-border text-stone-700 hover:bg-surface text-[11px] transition-std"
              @click="setActive(m.id)"
            >设为使用</button>
            <span v-else class="flex-1 px-2 py-1.5 rounded-lg text-center text-[11px] text-stone-400 bg-surface border border-border">当前模型</span>
            <button class="px-2 py-1.5 rounded-lg border border-border text-stone-500 hover:text-stone-800 hover:bg-surface transition-std" title="编辑" @click="startEdit(m)">
              <span v-html="ico('pencil')" />
            </button>
            <button
              class="px-2 py-1.5 rounded-lg border border-border text-stone-500 hover:text-rose-600 hover:bg-surface transition-std"
              :class="{ 'opacity-40 cursor-not-allowed': m.id === activeId }"
              title="删除"
              @click="m.id !== activeId && removeModel(m)"
            >
              <span v-html="ico('x')" />
            </button>
          </div>
        </div>
      </div>

      <!-- 联网工具：webfetch 内置零配置；websearch 需开启并配置 Tavily API Key -->
      <div class="bg-card rounded-xl border border-border shadow-card p-4">
        <div class="flex items-center gap-2.5 mb-3">
          <span class="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/25 flex items-center justify-center text-purple-700" v-html="ico('globe')" />
          <div>
            <div class="font-bold text-stone-900 text-[13px]">联网工具</div>
            <div class="text-[10.5px] text-stone-500">webfetch 抓取网页正文已内置（零配置）；websearch 联网搜索需配置 Tavily API Key</div>
          </div>
        </div>

        <!-- 开关：启用联网搜索 -->
        <div class="flex items-center justify-between bg-surface border border-border rounded-lg px-3 py-2.5 mb-2.5">
          <div>
            <div class="text-[12px] text-stone-800 font-medium">启用联网搜索（websearch）</div>
            <div class="text-[10px] text-stone-500">开启后模型可搜索实时信息；每次联网仍按权限模式请求确认</div>
          </div>
          <button
            type="button"
            role="switch"
            :aria-checked="web.enabled"
            class="relative w-10 h-5 shrink-0 rounded-full transition-std"
            :class="web.enabled ? 'bg-purple-600' : 'bg-stone-300'"
            @click="web.enabled = !web.enabled"
          >
            <span class="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-std" :class="web.enabled ? 'translate-x-5' : ''" />
          </button>
        </div>

        <!-- Tavily API Key -->
        <div class="mb-2.5">
          <div class="text-[10px] text-stone-500 mb-1">
            Tavily API Key <span class="text-stone-400">（{{ webKeyHint }} · 本机加密存储）</span>
          </div>
          <div class="flex items-center gap-2">
            <input
              v-model="webKey"
              type="password"
              placeholder="tvly-..."
              class="flex-1 bg-surface border border-border rounded-lg px-3 py-2 text-[12px] font-mono outline-none focus:border-accent/50 transition-std"
            />
            <button
              v-if="web.hasKey"
              class="px-3 py-2 rounded-lg border border-border text-stone-500 hover:text-rose-600 hover:bg-surface text-[11px] transition-std shrink-0"
              title="清除已存 Key"
              @click="clearWebKey"
            >清除</button>
          </div>
          <div class="text-[9.5px] text-stone-400 mt-1">
            在 <span class="font-mono">tavily.com</span> 免费注册获取 Key（tvly- 开头）；未配置时 websearch 不会下发给模型
          </div>
        </div>

        <div v-if="webError" class="flex items-center gap-1.5 text-[11px] text-rose-600 mb-2"><span v-html="ico('alert')" /> {{ webError }}</div>

        <div class="flex items-center justify-end">
          <button
            class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-stone-900 text-amber-50 hover:bg-stone-800 text-[11.5px] transition-std"
            @click="saveWeb"
          >
            <span v-html="ico(webSaved ? 'check' : 'shield')" /> {{ webSaved ? '已保存' : '保存联网设置' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 新增 / 编辑模型弹框（高级参数不暴露，对齐主流 Agent） -->
    <div
      v-if="editing"
      class="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/30 backdrop-blur-[2px]"
      @mousedown="overlay.onOverlayDown"
      @click="overlay.onOverlayClick"
    >
      <div class="w-[520px] bg-card border border-border rounded-2xl shadow-popover overflow-hidden">
        <div class="flex items-center gap-2.5 px-4 pt-4 pb-3">
          <span class="w-8 h-8 rounded-full bg-blue-500/10 border border-blue-500/30 flex items-center justify-center text-blue-700" v-html="ico('cpu')" />
          <div>
            <div class="text-[13px] font-semibold text-stone-900">{{ editingId ? '编辑模型' : '新增模型' }}</div>
            <div class="text-[10.5px] text-stone-500">OpenAI 兼容接口 · 温度 / 上下文等参数已自动优化，无需配置</div>
          </div>
          <button class="ml-auto text-stone-400 hover:text-stone-600" v-html="ico('x')" @click="cancelEdit" />
        </div>

        <div class="px-4 pb-3 space-y-2.5">
          <div class="grid grid-cols-2 gap-2.5">
            <div>
              <div class="text-[10px] text-stone-500 mb-1">配置名称</div>
              <input v-model="form.name" placeholder="如：主力模型" class="w-full bg-surface border border-border rounded-lg px-3 py-2 text-[12px] outline-none focus:border-accent/50 transition-std" />
            </div>
            <div>
              <div class="text-[10px] text-stone-500 mb-1">厂商</div>
              <div class="relative">
                <img v-if="logoOf(form.provider)" :src="logoOf(form.provider)" class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 object-contain" alt="" />
                <span v-else class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-stone-500" v-html="ico('cpu')" />
                <select
                  :value="form.provider"
                  class="w-full appearance-none bg-surface border border-border rounded-lg pl-8 pr-6 py-2 text-[12px] outline-none cursor-pointer focus:border-accent/50 transition-std"
                  @change="onProviderChange(($event.target as HTMLSelectElement).value)"
                >
                  <option v-for="p in PROVIDERS" :key="p" :value="p">{{ p }}</option>
                </select>
                <span class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[8px] text-stone-400">▼</span>
              </div>
              <div class="text-[9px] text-stone-400 mt-1">{{ PROVIDER_PRESET[form.provider]?.hint ?? '' }}</div>
            </div>
          </div>
          <div>
            <div class="text-[10px] text-stone-500 mb-1">Base URL</div>
            <input v-model="form.baseUrl" placeholder="https://api.openai.com/v1" class="w-full bg-surface border border-border rounded-lg px-3 py-2 text-[12px] font-mono outline-none focus:border-accent/50 transition-std" />
          </div>
          <div>
            <div class="text-[10px] text-stone-500 mb-1">模型 ID</div>
            <input v-model="form.model" :placeholder="PROVIDER_PRESET[form.provider]?.model ?? ''" class="w-full bg-surface border border-border rounded-lg px-3 py-2 text-[12px] font-mono outline-none focus:border-accent/50 transition-std" />
          </div>
          <div>
            <div class="text-[10px] text-stone-500 mb-1">API Key <span class="text-stone-400">（{{ keyHint }} · 本机加密存储）</span></div>
            <input
              v-model="form.apiKey"
              type="password"
              :placeholder="editingModel?.apiKeyMask ? '留空 = 保留当前 Key；输入新值 = 重新设置' : 'sk-...'"
              class="w-full bg-surface border border-border rounded-lg px-3 py-2 text-[12px] font-mono outline-none focus:border-accent/50 transition-std"
            />
          </div>
          <div v-if="error" class="flex items-center gap-1.5 text-[11px] text-rose-600"><span v-html="ico('alert')" /> {{ error }}</div>
        </div>

        <div class="px-4 pb-4 flex items-center justify-end gap-2">
          <button
            class="px-3.5 py-1.5 rounded-lg border border-border text-stone-600 hover:bg-surface text-[11.5px] transition-std"
            @click="cancelEdit"
          >取消</button>
          <button
            class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-stone-900 text-amber-50 hover:bg-stone-800 text-[11.5px] transition-std"
            @click="save"
          >
            <span v-html="ico(saved ? 'check' : 'plus')" /> {{ saved ? '已保存' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
