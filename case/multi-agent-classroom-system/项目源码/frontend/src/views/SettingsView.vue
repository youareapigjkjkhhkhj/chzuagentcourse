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

import ProviderCardPanel from '@/components/ProviderCard.vue'
import ProviderFormDrawer from '@/components/ProviderFormDrawer.vue'
import { describeError, useSettingsStore } from '@/stores/settings'
import type {
  GenerationSettings,
  Intonation,
  Intensity,
  ProviderCard,
  ScriptDetail,
  VoiceSettings,
} from '@/types/api'

const settings = useSettingsStore()

type PaneKey = 'model' | 'voice' | 'gen' | 'about'

/** 菜单项与图标名对应原型 settings.html 的四个 .set-menu__item。 */
const PANES: { key: PaneKey; label: string; icon: 'chip' | 'mic' | 'sliders' | 'info' }[] = [
  { key: 'model', label: '模型服务', icon: 'chip' },
  { key: 'voice', label: '语音服务', icon: 'mic' },
  { key: 'gen', label: '生成参数', icon: 'sliders' },
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
              <div>
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
            </div>
          </div>

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
          </div>
        </section>
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

<style scoped>
/* 版式取自 产品原型/settings.html（.set-wrap / .set-menu / .set-card / .provider / .voice-card / .save-bar） */

.set-wrap {
  display: flex;
  max-width: 1080px;
  margin: 32px auto;
  padding: 0 32px;
  gap: 24px;
  align-items: flex-start;
}

.set-menu {
  width: 220px;
  flex-shrink: 0;
  padding: 8px;
  position: sticky;
  top: 92px;
}

.set-menu__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  font-size: 14px;
  color: var(--td-text-secondary);
  border-radius: var(--td-radius-default);
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 2px;
}

.set-menu__item:hover {
  background: var(--td-bg-container-hover);
  color: var(--td-text-primary);
}

.set-menu__item.is-active {
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
  font-weight: 600;
}

.set-menu__item svg {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
}

.set-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.full {
  width: 100%;
}

.field-label {
  display: block;
  font-size: 13px;
  color: var(--td-text-secondary);
  margin-bottom: 10px;
}

.voice-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 8px;
}

@media (max-width: 900px) {
  .voice-grid {
    grid-template-columns: 1fr;
  }
}

.voice-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--td-component-border);
  border-radius: var(--td-radius-medium);
  cursor: pointer;
  transition: all 0.2s;
}

.voice-card:hover {
  border-color: var(--td-brand-color);
}

.voice-card.is-checked {
  border-color: var(--td-brand-color);
  background: var(--td-brand-color-light);
}

.voice-card :deep(.t-avatar) {
  width: 38px;
  height: 38px;
}

.v-name {
  font-size: 13.5px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.v-desc {
  font-size: 12px;
  color: var(--td-text-placeholder);
  margin-top: 2px;
}

.slider-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 0;
}

.sl-label {
  width: 130px;
  flex-shrink: 0;
  font-size: 13.5px;
}

.slider-row :deep(.t-slider__container) {
  flex: 1;
}

.sl-val {
  width: 44px;
  text-align: right;
  font-family: var(--td-font-mono);
  font-size: 13px;
  color: var(--td-brand-color);
}

.switches {
  border-top: 1px solid var(--td-component-stroke);
  margin-top: 12px;
  padding-top: 8px;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  font-size: 14px;
}

.tip {
  font-size: 12px;
  color: var(--td-text-secondary);
  line-height: 1.7;
  margin: 4px 0 0;
}

.save-bar {
  position: sticky;
  bottom: 24px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 14px 20px;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-2);
}

.about {
  text-align: center;
  padding: 56px 28px;
}

.about__mark {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  background: var(--td-brand-color);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}

.about h3 {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 8px;
}

.about .muted {
  margin-bottom: 4px;
}

.about__tags {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 20px;
}

.about__note {
  font-size: 12px;
  color: var(--td-text-secondary);
  margin-top: 16px;
}
</style>
