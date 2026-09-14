<script setup lang="ts">
/**
 * 设置页（P0-A3 ~ P0-A7）。四个分区对应原型的左侧菜单。
 *
 * 交互上只做一件事：**改动先落进 draft，点「保存设置」才写库**。
 * 滑杆每动一下就发一次请求的实现很省事，但会把「用户试了几个值」
 * 变成一串没必要的写操作，也没法给一个明确的成功反馈。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

import * as api from '@/api'
import BudgetEditor from '@/components/BudgetEditor.vue'
import CostBoard from '@/components/CostBoard.vue'
import PricingEditor from '@/components/PricingEditor.vue'
import ProviderCardPanel from '@/components/ProviderCard.vue'
import ProviderFormDrawer from '@/components/ProviderFormDrawer.vue'
import { describeError, useSettingsStore } from '@/stores/settings'
import { formatCost, formatUnits } from '@/utils/voice'
import type {
  GenerationSettings,
  Intonation,
  Intensity,
  ProviderCard,
  ScriptDetail,
  UsageKind,
  UsageReport,
  VoiceList,
  VoiceProfile,
  VoiceSettings,
} from '@/types/api'

const settings = useSettingsStore()

type PaneKey = 'model' | 'voice' | 'gen' | 'cost' | 'about'

/** 菜单项与图标名对应原型 settings.html 的四个 .set-menu__item（「成本」是 P5 新增的第五个）。 */
const PANES: { key: PaneKey; label: string; icon: 'chip' | 'mic' | 'sliders' | 'chart' | 'info' }[] =
  [
    { key: 'model', label: '模型服务', icon: 'chip' },
    { key: 'voice', label: '语音服务', icon: 'mic' },
    { key: 'gen', label: '生成参数', icon: 'sliders' },
    { key: 'cost', label: '成本与预算', icon: 'chart' },
    { key: 'about', label: '关于', icon: 'info' },
  ]

/** 音色卡头像的渐变，按顺序取自原型的三个声音（蓝 / 绿 / 橙，多出来的走紫）。 */
const VOICE_AVATARS = [
  'linear-gradient(135deg,#0052d9,#618eff)',
  'linear-gradient(135deg,#00a870,#33c68f)',
  'linear-gradient(135deg,#ed7b2f,#f5a06b)',
  'linear-gradient(135deg,#6a5fd0,#948be0)',
]

function voiceAvatar(index: number): string {
  return VOICE_AVATARS[index % VOICE_AVATARS.length] as string
}

const activePane = ref<PaneKey>('model')
const drawerVisible = ref(false)
const editing = ref<ProviderCard | null>(null)
const probingId = ref('')
const saving = ref(false)

// --- 草稿 ---

const voiceDraft = reactive<VoiceSettings>({
  voices: [],
  teacherVoiceId: '',
  speed: 1,
  intonation: 'natural',
  asrEnabled: true,
  asrBrowserLocal: true,
})

const genDraft = reactive<GenerationSettings>({
  pageCount: 12,
  classmateCount: 3,
  intensity: 'medium',
  scriptDetail: 'detailed',
  autoIllustration: true,
  quizPerChapter: true,
  whiteboard: true,
  socraticAnswer: true,
})

/** 后端返回后铺一次草稿。用户正在改的时候不覆盖（watch 的是数据本身，不是每次渲染）。 */
watch(
  () => settings.voice,
  (value) => {
    if (value) Object.assign(voiceDraft, value)
  },
  { immediate: true },
)

watch(
  () => settings.generation,
  (value) => {
    if (value) Object.assign(genDraft, value)
  },
  { immediate: true },
)

const limits = computed(() => settings.limits)
const speedText = computed(() => `${voiceDraft.speed.toFixed(1)}x`)

/**
 * 当前启用的文本模型（P4-F5 那半句「材料将发送给 XX 服务商处理」）。
 *
 * 材料分块只拼进 `registry.current_llm()` 那一次的 messages 里，所以「发给谁」
 * 就是这里显示的这一家；一家都没启用时材料发不出去，得如实说，不能留白。
 */
const activeLlm = computed(() => settings.llmProviders.find((card) => card.enabled) ?? null)
const materialNotice = computed(() =>
  activeLlm.value
    ? `上传的讲义会被解析成分块存下来；生成课程时，只把这些分块发给当前启用的「${activeLlm.value.name}」。`
    : '上传的讲义会被解析成分块存下来；当前没有启用任何文本模型，生成课程时材料不会被发往任何服务商。',
)

const INTONATION_LABELS: Record<Intonation, string> = {
  flat: '平稳',
  natural: '自然',
  expressive: '起伏',
}

const INTENSITY_LABELS: Record<Intensity, string> = {
  low: '温和',
  medium: '适中',
  high: '激烈',
}

const SCRIPT_LABELS: Record<ScriptDetail, string> = {
  concise: '精简',
  normal: '标准',
  detailed: '详细',
}

const intonationOptions = computed(() =>
  (limits.value?.intonations ?? ['flat', 'natural', 'expressive']).map((value) => ({
    value,
    label: INTONATION_LABELS[value],
  })),
)

const intensityOptions = computed(() =>
  (limits.value?.intensities ?? ['low', 'medium', 'high']).map((value) => ({
    value,
    label: INTENSITY_LABELS[value],
  })),
)

const scriptOptions = computed(() =>
  (limits.value?.scriptDetails ?? ['concise', 'normal', 'detailed']).map((value) => ({
    value,
    label: SCRIPT_LABELS[value],
  })),
)

const teacherVoices = computed(() => voiceDraft.voices)

// --- 试听与用量（P2-A5 / P2-A11 / F2-10 / F2-11）---

/** `/api/voice/voices` 那份视图：比设置页的音色表多一个 `usable`。读不到就是 null。 */
const voiceList = ref<VoiceList | null>(null)
const voiceListError = ref('')
const previewingId = ref('')
/** 试听的文本。留空就用服务端的示例句（P2-A5 的「固定示例句」）。 */
const previewText = ref('')

const usage = ref<UsageReport | null>(null)
const usageError = ref('')
/** 空串 = 全部；否则是一门课的 id。P2-A11 要看的是「本次课堂」。 */
const usageScope = ref('')
const courseOptions = ref<{ label: string; value: string }[]>([])

/** 同一时刻只留一段试听在响：再点一次就把上一段停掉。 */
let previewAudio: HTMLAudioElement | null = null

const USAGE_LABELS: Record<UsageKind, string> = {
  tts: '语音合成（讲稿、试听）',
  realtime: '实时语音（课堂问答）',
  asr: '语音识别（上传识别）',
}

/** 用量行里有数字才值得显示 —— 三类全零时给一句话，不给三行 0。 */
const usageRows = computed(() => (usage.value?.kinds ?? []).filter((row) => row.calls > 0))
const usageEmpty = computed(() => Boolean(usage.value) && usageRows.value.length === 0)

/**
 * 音色卡的「试听」亮不亮。
 *
 * 先看语音功能那份视图（`usable` = 声音 ID 配了**且**服务商可用）；那份还没读回来
 * （或读失败）时退到设置里已有的 `configured` —— 这是**少说一句「能用」**的方向，
 * 不会把一个点下去只会报错的按钮说成能点。
 */
function usableOf(voice: VoiceProfile): boolean {
  const row = voiceList.value?.items.find((item) => item.id === voice.id)
  return row ? row.usable : voice.configured
}

function usableReasonOf(voice: VoiceProfile): string {
  if (usableOf(voice)) return `试听「${voice.name}」`
  if (!voice.configured) return '这把音色还没配厂商声音 ID，配好才能出声'
  return '语音服务商目前不可用，去「模型服务」里检查凭据'
}

/** 播放一小段音频。**合成成功**与**浏览器拦下播放**是两件事，不混成一个错。 */
function playClip(url: string): void {
  previewAudio?.pause()
  previewAudio = new Audio(url)
  void previewAudio.play().catch(() => {
    MessagePlugin.info('浏览器拦下了播放：点一下页面再试')
  })
}

async function onPreview(voice: VoiceProfile): Promise<void> {
  previewingId.value = voice.id
  try {
    const result = await api.previewVoice(voice.id, { text: previewText.value.trim() })
    playClip(result.url)
    MessagePlugin.success(
      result.cached
        ? `${voice.name}：这一段是上次合成的，没有重复计费`
        : `${voice.name} 试听中 · ${(result.durationMs / 1000).toFixed(1)} 秒`,
    )
  } catch (error) {
    // 没配声音 ID / 服务商不可用都会落到这里，原因原样给出来 ——
    // 设置页正是修这个的地方，别只说一句「试听失败」
    MessagePlugin.error(describeError(error))
  } finally {
    previewingId.value = ''
  }
}

async function refreshUsage(): Promise<void> {
  try {
    usage.value = await api.fetchVoiceUsage(
      usageScope.value ? { refType: 'course', refId: usageScope.value } : {},
    )
    usageError.value = ''
  } catch (error) {
    usage.value = null
    usageError.value = describeError(error)
  }
}

async function onUsageScope(value: string): Promise<void> {
  usageScope.value = value
  await refreshUsage()
}

/** 语音这一屏要的三份数据一起读：音色视图、用量、课程下拉（失败了也不必挡住别的）。 */
async function loadVoiceExtras(): Promise<void> {
  try {
    voiceList.value = await api.fetchVoices()
    voiceListError.value = ''
  } catch (error) {
    voiceList.value = null
    voiceListError.value = describeError(error)
  }
  try {
    const list = await api.fetchCourses({ size: 50 })
    courseOptions.value = list.items.map((item) => ({ label: item.title, value: item.id }))
  } catch {
    // 课程读不到只是少了「按课程看用量」这一档：选择器退回「全部」，不报错
    courseOptions.value = []
  }
  await refreshUsage()
}

/** 当前草稿与已保存值有没有差别 —— 决定「保存设置」按钮是否可点。 */
const voiceDirty = computed(() => {
  const saved = settings.voice
  if (!saved) return false
  return (
    voiceDraft.teacherVoiceId !== saved.teacherVoiceId ||
    voiceDraft.speed !== saved.speed ||
    voiceDraft.intonation !== saved.intonation ||
    voiceDraft.asrEnabled !== saved.asrEnabled ||
    voiceDraft.asrBrowserLocal !== saved.asrBrowserLocal
  )
})

const genDirty = computed(() => {
  const saved = settings.generation
  if (!saved) return false
  return (Object.keys(genDraft) as (keyof GenerationSettings)[]).some(
    (key) => genDraft[key] !== saved[key],
  )
})

const canSave = computed(() => {
  if (activePane.value === 'voice') return voiceDirty.value
  if (activePane.value === 'gen') return genDirty.value
  return false
})

/**
 * 这一屏有没有「草稿」这回事。
 *
 * 「模型服务」与「关于」是即时生效 / 只读的：那边一条待保存的改动都不存在，
 * 摆一条永远点不动的「保存设置」只会让人以为设置坏了。所以整条保存栏
 * 只在这两屏（语音服务 / 生成参数）出现。
 */
const isDraftPane = computed(() => activePane.value === 'voice' || activePane.value === 'gen')

// --- 动作 ---

function openDrawer(card: ProviderCard) {
  editing.value = card
  drawerVisible.value = true
}

async function onEnable(card: ProviderCard) {
  try {
    await settings.enable(card.id)
    MessagePlugin.success(`已切换到 ${card.name}`)
  } catch (error) {
    MessagePlugin.error(describeError(error))
  }
}

async function onTest(card: ProviderCard) {
  probingId.value = card.id
  try {
    const result = await settings.probe(card.id)
    if (result.ok) {
      MessagePlugin.success(
        `${card.name} 连接成功${result.latencyMs ? ` · ${result.latencyMs}ms` : ''}`,
      )
    } else {
      MessagePlugin.error(`${card.name}：${result.error || '连接失败'}`)
    }
  } catch (error) {
    MessagePlugin.error(describeError(error))
  } finally {
    probingId.value = ''
  }
}

async function onSave() {
  saving.value = true
  try {
    if (activePane.value === 'voice') {
      await settings.saveVoice({
        teacherVoiceId: voiceDraft.teacherVoiceId,
        speed: voiceDraft.speed,
        intonation: voiceDraft.intonation,
        asrEnabled: voiceDraft.asrEnabled,
        asrBrowserLocal: voiceDraft.asrBrowserLocal,
      })
    } else if (activePane.value === 'gen') {
      await settings.saveGeneration({
        pageCount: genDraft.pageCount,
        classmateCount: genDraft.classmateCount,
        intensity: genDraft.intensity,
        scriptDetail: genDraft.scriptDetail,
        autoIllustration: genDraft.autoIllustration,
        quizPerChapter: genDraft.quizPerChapter,
        whiteboard: genDraft.whiteboard,
        socraticAnswer: genDraft.socraticAnswer,
      })
    }
    MessagePlugin.success('设置已保存')
  } catch (error) {
    // 后端会校验范围（页数 8~20 等），越界的原因原样显示
    MessagePlugin.error(describeError(error))
  } finally {
    saving.value = false
  }
}

function onReset() {
  if (activePane.value === 'voice' && settings.voice) Object.assign(voiceDraft, settings.voice)
  if (activePane.value === 'gen' && settings.generation) Object.assign(genDraft, settings.generation)
  MessagePlugin.info('已还原为上次保存的值')
}

/**
 * 切到「语音服务」就去拉试听与用量那两份数据。
 *
 * 每次进这一屏都重拉：用量是会变的（刚在课堂里说了几句话），
 * 而这一屏本来就是「看一眼现在什么情况」的地方，缓存只会给一个过期的数字。
 */
watch(
  activePane,
  (pane) => {
    if (pane === 'voice') void loadVoiceExtras()
  },
  { immediate: true },
)

onMounted(() => {
  void settings.loadAll()
})
</script>

<template>
  <div class="set-wrap">
    <aside class="panel set-menu">
      <div
        v-for="pane in PANES"
        :key="pane.key"
        class="set-menu__item"
        :class="{ 'is-active': activePane === pane.key }"
        @click="activePane = pane.key"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <template v-if="pane.icon === 'chip'">
            <rect x="5" y="5" width="14" height="14" rx="2" />
            <path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" />
          </template>
          <template v-else-if="pane.icon === 'mic'">
            <path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3Z" />
            <path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7" />
          </template>
          <template v-else-if="pane.icon === 'sliders'">
            <path d="M4 8h10M18 8h2M4 16h2M10 16h10" />
            <circle cx="16" cy="8" r="2" />
            <circle cx="8" cy="16" r="2" />
          </template>
          <!-- 成本：一根有涨有落的柱子 -->
          <template v-else-if="pane.icon === 'chart'">
            <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
          </template>
          <template v-else>
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8h.01M12 11v5" />
          </template>
        </svg>
        {{ pane.label }}
      </div>
    </aside>

    <div class="set-main">
      <t-alert v-if="settings.lastError" theme="error" :title="settings.lastError" class="full" />

      <!-- 模型服务 -->
      <template v-if="activePane === 'model'">
        <section class="panel">
          <h3 class="panel__title">模型服务商</h3>
          <p class="panel__desc">
            配置大语言模型来源，课程大纲、讲稿与课堂对话均由所选模型驱动。
            五家都走 OpenAI 兼容协议，差异只在接入地址与模型名。
          </p>

          <ProviderCardPanel
            v-for="card in settings.llmProviders"
            :key="card.id"
            :card="card"
            :probing="probingId === card.id"
            @configure="openDrawer"
            @enable="onEnable"
            @test="onTest"
          />

          <p class="tip">
            {{ materialNotice }}
            想先确认这一点再上传材料，就在这儿看：换一家启用的服务商，材料也就跟着换一家收。
          </p>

          <p class="tip">
            语音合成 / 语音识别 / 实时语音的设置在同页的「语音服务」里 ——
            它们与文本模型是三套独立的能力，混在一起会让人以为换了文本模型就换了声音。
          </p>
        </section>
      </template>

      <!-- 语音服务 -->
      <template v-else-if="activePane === 'voice'">
        <section class="panel">
          <h3 class="panel__title">语音合成（TTS）</h3>
          <p class="panel__desc">
            AI 教师与 AI 同学的授课、发言声音。音色卡下方的状态来自「这把音色有没有配到
            具体的厂商声音 ID」—— 填了才出声，没填就只是名字。
          </p>

          <label class="field-label">AI 教师默认音色</label>
          <div class="voice-grid">
            <div
              v-for="(voice, index) in teacherVoices"
              :key="voice.id"
              class="voice-card"
              :class="{ 'is-checked': voiceDraft.teacherVoiceId === voice.id }"
              @click="voiceDraft.teacherVoiceId = voice.id"
            >
              <t-avatar :style="{ background: voiceAvatar(index) }" shape="circle">
                {{ voice.name.slice(0, 1) }}
              </t-avatar>
              <div class="v-body">
                <div class="v-name">
                  {{ voice.name }}
                  <t-tag
                    v-if="voice.configured"
                    size="small"
                    theme="success"
                    variant="light"
                  >
                    已配声音
                  </t-tag>
                  <t-tag v-else size="small" variant="light">未配声音 ID</t-tag>
                </div>
                <div class="v-desc">{{ voice.style }}</div>
              </div>
              <!-- 试听是卡片上的一个独立动作：点卡片是「选它」，点这里是「听它」，
                   两件事不能共用一次点击（选音色和听音色常常不是同一刻想做的） -->
              <t-button
                class="v-audio"
                size="small"
                variant="outline"
                :disabled="!usableOf(voice)"
                :loading="previewingId === voice.id"
                :title="usableReasonOf(voice)"
                @click.stop="onPreview(voice)"
              >
                试听
              </t-button>
            </div>
          </div>

          <div class="preview-row">
            <t-input
              v-model="previewText"
              placeholder="留空就用默认示例句（试听同一句话会命中缓存、不重复计费）"
              :maxlength="60"
            />
          </div>

          <t-alert v-if="voiceListError" theme="warning" class="pane-hint">
            <template #message>
              读不到语音服务状态（{{ voiceListError }}）——「试听」按钮暂时按
              「这把音色配没配声音 ID」显示。
            </template>
          </t-alert>

          <div class="slider-row">
            <span class="sl-label">语速</span>
            <t-slider
              v-model="voiceDraft.speed"
              :min="limits?.minSpeed ?? 0.5"
              :max="limits?.maxSpeed ?? 2.0"
              :step="0.1"
            />
            <span class="sl-val mono">{{ speedText }}</span>
          </div>

          <div class="slider-row">
            <span class="sl-label">语调起伏</span>
            <t-radio-group v-model="voiceDraft.intonation" variant="default-filled">
              <t-radio-button
                v-for="option in intonationOptions"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </t-radio-button>
            </t-radio-group>
          </div>
        </section>

        <section class="panel">
          <h3 class="panel__title">语音识别（ASR）</h3>
          <p class="panel__desc">
            学生举手发言时的语音识别，用于把语音转成文字进入课堂讨论。
          </p>
          <div class="switch-row">
            <span>启用语音发言（按住空格说话）</span>
            <t-switch v-model="voiceDraft.asrEnabled" />
          </div>
          <div class="switch-row">
            <span>浏览器本地识别（Web Speech API，无需密钥）</span>
            <t-switch v-model="voiceDraft.asrBrowserLocal" />
          </div>
        </section>

        <!-- 用量与费用（P2-A11 / F2-10）：数字全部来自 usage_records 求和 -->
        <section class="panel">
          <div class="panel__head">
            <h3 class="panel__title">用量与费用</h3>
            <t-select
              v-model="usageScope"
              class="usage-scope"
              :options="[{ label: '全部课堂', value: '' }, ...courseOptions]"
              size="small"
              @change="onUsageScope($event as string)"
            />
          </div>
          <p class="panel__desc">
            按调用上游的真实计量口径记账：合成记字符数、实时语音与识别记秒数。
            金额是按配置里的价目表**估算**的，与账单可能有出入。
          </p>

          <t-alert v-if="usageError" theme="error">
            <template #message>读不到用量：{{ usageError }}</template>
          </t-alert>

          <template v-else-if="usage">
            <div v-if="usageEmpty" class="usage-empty">
              还没有产生用量：合成一次讲稿、或在课堂里说几句话，这里就有数字了。
            </div>
            <div v-else class="usage-table">
              <div class="usage-head">
                <span>链路</span><span>计量</span><span>次数</span><span>估算费用</span>
              </div>
              <div v-for="row in usageRows" :key="row.kind" class="usage-row">
                <span>{{ USAGE_LABELS[row.kind] }}</span>
                <span class="mono">{{ formatUnits(row.unitName, row.units) }}</span>
                <span class="mono">{{ row.calls }}</span>
                <span class="mono">{{ formatCost(row.estCost) }}</span>
              </div>
              <div class="usage-total">
                <span>合计</span>
                <span class="mono">{{ formatCost(usage.totalCost) }}</span>
              </div>
            </div>
            <p v-if="!usage.priced" class="usage-note">
              有链路还没配单价（VOICE_*_PRICE_*），上面的合计是
              <b>少报</b>
              的 —— 所以这里说的是「未配置单价」，而不是一个看起来不花钱的 ¥0.00。
            </p>
          </template>
        </section>
      </template>

      <!-- 生成参数 -->
      <template v-else-if="activePane === 'gen'">
        <section class="panel">
          <h3 class="panel__title">课堂生成参数</h3>
          <p class="panel__desc">
            控制 AI 生成课程的规模、节奏与互动强度，对之后创建的所有课堂生效。
            范围与后端校验用的是同一份常量（来自 /api/capabilities）。
          </p>

          <div class="slider-row">
            <span class="sl-label">默认课件页数</span>
            <t-slider
              v-model="genDraft.pageCount"
              :min="limits?.minPageCount ?? 8"
              :max="limits?.maxPageCount ?? 20"
              :step="1"
            />
            <span class="sl-val mono">{{ genDraft.pageCount }} 页</span>
          </div>

          <div class="slider-row">
            <span class="sl-label">AI 同学数量</span>
            <t-slider
              v-model="genDraft.classmateCount"
              :min="limits?.minClassmateCount ?? 0"
              :max="limits?.maxClassmateCount ?? 5"
              :step="1"
            />
            <span class="sl-val mono">{{ genDraft.classmateCount }} 位</span>
          </div>

          <div class="slider-row">
            <span class="sl-label">讨论激烈程度</span>
            <t-radio-group v-model="genDraft.intensity" variant="default-filled">
              <t-radio-button
                v-for="option in intensityOptions"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </t-radio-button>
            </t-radio-group>
          </div>

          <div class="slider-row">
            <span class="sl-label">讲稿详细程度</span>
            <t-radio-group v-model="genDraft.scriptDetail" variant="default-filled">
              <t-radio-button
                v-for="option in scriptOptions"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </t-radio-button>
            </t-radio-group>
          </div>

          <div class="switches">
            <div class="switch-row">
              <span>自动配图与示意图</span>
              <t-switch v-model="genDraft.autoIllustration" />
            </div>
            <div class="switch-row">
              <span>每章结束自动生成随堂测验</span>
              <t-switch v-model="genDraft.quizPerChapter" />
            </div>
            <div class="switch-row">
              <span>允许课堂中使用白板</span>
              <t-switch v-model="genDraft.whiteboard" />
            </div>
            <div class="switch-row">
              <span>学生提问时先引导思考，再给答案</span>
              <t-switch v-model="genDraft.socraticAnswer" />
            </div>
          </div>
        </section>
      </template>

      <!-- 成本与预算（P5 §4.2 / F5-7 / F5-8）：看板 → 预算 → 价目表，
           从上到下就是「花了多少 → 花到哪条线为止 → 按什么价算的」 -->
      <template v-else-if="activePane === 'cost'">
        <CostBoard />
        <BudgetEditor />
        <PricingEditor />
      </template>

      <!-- 关于 -->
      <template v-else>
        <section class="panel about">
          <div class="about__mark">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
              <path
                d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H13l-4 4v-4H5.5A1.5 1.5 0 0 1 4 14.5v-9Z"
                fill="#fff"
              />
              <circle cx="9" cy="10" r="1.2" fill="#0052d9" />
              <circle cx="12.5" cy="10" r="1.2" fill="#0052d9" />
              <circle cx="16" cy="10" r="1.2" fill="#0052d9" />
            </svg>
          </div>
          <h3>EduAgentX 多智能体互动课堂</h3>
          <p class="muted">
            当前环境：{{ settings.capabilities?.env ?? '—' }} ·
            版本 v{{ settings.capabilities?.version ?? '—' }}
          </p>
          <p class="muted">
            数据库：{{ settings.health?.db ?? '—' }} ·
            文本模型：{{ settings.health?.llm.provider ?? '—' }}
            {{ settings.health?.llm.model ? `(${settings.health.llm.model})` : '' }}
          </p>
          <div class="about__tags">
            <t-tag theme="primary" variant="light">v{{ settings.capabilities?.version ?? '—' }}</t-tag>
            <t-tag variant="light">TDesign 风格</t-tag>
            <t-tag variant="light">Flask + Vue3 + SQLite</t-tag>
          </div>
          <p class="about__note">
            本页显示的每个状态都取自服务端的真实探测结果；
            「已配置」与「可用」是两件事，卡片上分开显示。
          </p>
        </section>
      </template>

      <div v-if="isDraftPane" class="save-bar">
        <t-button variant="outline" :disabled="!canSave" @click="onReset">还原</t-button>
        <t-button theme="primary" :loading="saving" :disabled="!canSave" @click="onSave">
          保存设置
        </t-button>
      </div>
    </div>

    <ProviderFormDrawer v-model:visible="drawerVisible" :card="editing" />
  </div>
</template>
<style scoped src="../styles/views/SettingsView.css"></style>
