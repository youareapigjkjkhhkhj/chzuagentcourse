<script setup lang="ts">
/**
 * 服务商配置抽屉（P0-A4 / P0-A5 / P0-F2）。
 *
 * 三个容易做错的地方，都在这里明确处理：
 *
 * 1. **Key 的回显是掩码，不是明文。** 后端从不回传明文（`maskedKey: "sk-****1234"`），
 *    所以输入框留空 = 不改动原来的 Key。用户想换 Key 才输入新值。
 * 2. **「测试连接」测的是已保存的配置。** 后端拿库里的（或 .env 的）凭据去连，
 *    所以表单一脏就先保存再测，否则测的是旧 Key，用户会以为新 Key 不行。
 * 3. **失败原因原样显示。** 探活返回 `{ok:false, error, errorCode}` 而不是抛异常，
 *    401 就显示 401 的原因 —— 弹一句「操作成功」等于把排障线索扔掉。
 */
import { computed, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

import { describeError, useSettingsStore } from '@/stores/settings'
import type { ProbeResult, ProviderCard } from '@/types/api'

const props = defineProps<{
  visible: boolean
  card: ProviderCard | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  saved: [card: ProviderCard]
}>()

const settings = useSettingsStore()

const apiKey = ref('')
const baseUrl = ref('')
const defaultModel = ref('')
const keyVisible = ref(false)
const saving = ref(false)
const probing = ref(false)
const probeResult = ref<ProbeResult | null>(null)
const failure = ref('')

/** 打开抽屉时用卡片上的当前值铺一次表单。key 永远是空的（见文件头第 1 条）。 */
watch(
  () => [props.visible, props.card?.id] as const,
  ([visible]) => {
    if (!visible || !props.card) return
    apiKey.value = ''
    baseUrl.value = props.card.baseUrl
    defaultModel.value = props.card.defaultModel
    probeResult.value = null
    failure.value = ''
    keyVisible.value = false
  },
  { immediate: true },
)

const dirty = computed(() => {
  if (!props.card) return false
  return (
    apiKey.value !== '' ||
    baseUrl.value !== props.card.baseUrl ||
    defaultModel.value !== props.card.defaultModel
  )
})

const hasStoredKey = computed(() => Boolean(props.card?.maskedKey))

/** 测试连接的结果文案：成功给延迟，失败给原因。 */
const probeText = computed(() => {
  const result = probeResult.value
  if (!result) return ''
  if (result.ok) {
    const latency = result.latencyMs > 0 ? ` · ${result.latencyMs}ms` : ''
    const model = result.model ? ` · ${result.model}` : ''
    return `✓ 已连接${latency}${model}`
  }
  return `✗ ${result.error || '连接失败'}`
})

function close() {
  emit('update:visible', false)
}

function payload() {
  const body: Record<string, unknown> = {
    baseUrl: baseUrl.value,
    defaultModel: defaultModel.value,
  }
  // 空串 = 不改（后端语义），所以只在真的输入了才带上
  if (apiKey.value) body.apiKey = apiKey.value
  return body
}

async function save(): Promise<ProviderCard | null> {
  if (!props.card) return null
  saving.value = true
  failure.value = ''
  try {
    const card = await settings.saveProvider(props.card.id, payload())
    apiKey.value = '' // 保存后清掉明文，界面只留掩码
    probeResult.value = null
    MessagePlugin.success('设置已保存')
    emit('saved', card)
    return card
  } catch (error) {
    failure.value = describeError(error)
    MessagePlugin.error(failure.value)
    return null
  } finally {
    saving.value = false
  }
}

/**
 * 测试连接。表单一脏就先保存 —— 后端测的是**已保存**的配置，
 * 不保存就测等于拿旧 Key 得出「新 Key 不行」的结论。
 */
async function test() {
  if (!props.card) return
  probing.value = true
  failure.value = ''
  probeResult.value = null
  try {
    if (dirty.value) {
      const saved = await save()
      if (!saved) return
    }
    const result = await settings.probe(props.card.id)
    probeResult.value = result
    if (result.ok) {
      MessagePlugin.success(`连接成功${result.latencyMs ? ` · ${result.latencyMs}ms` : ''}`)
    } else {
      MessagePlugin.error(result.error || '连接失败')
    }
  } catch (error) {
    // 40201（没配 Key）会走到这里：后端的 message 就是说给用户听的那句
    failure.value = describeError(error)
    MessagePlugin.error(failure.value)
  } finally {
    probing.value = false
  }
}

async function onSave() {
  const card = await save()
  if (card) close()
}
</script>

<template>
  <t-drawer
    :visible="visible"
    :header="card ? `${card.name} 连接配置` : '连接配置'"
    size="520px"
    :footer="false"
    @close="close"
  >
    <p class="hint">
      凭据只保存在本机服务端（加密后写入 SQLite），浏览器永远不会拿到明文，
      更不会直连厂商接口。
    </p>

    <t-form label-align="top" @submit.prevent>
      <t-form-item label="API Key">
        <t-input
          v-model="apiKey"
          :type="keyVisible ? 'text' : 'password'"
          :placeholder="hasStoredKey ? `已保存 ${card?.maskedKey}，留空则不修改` : '请粘贴 API Key'"
        >
          <template #suffix-icon>
            <!-- 眼睛图标取自原型 settings.html 的 .key-input .eye -->
            <span
              class="eye"
              :title="keyVisible ? '隐藏' : '显示'"
              @click="keyVisible = !keyVisible"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
                <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
                <circle cx="12" cy="12" r="3" />
                <path v-if="!keyVisible" d="M4 20 20 4" />
              </svg>
            </span>
          </template>
        </t-input>
        <template #help>
          <span v-if="hasStoredKey" class="mono">当前已保存：{{ card?.maskedKey }}</span>
          <span v-else>留空则保留原值；输入新值会覆盖</span>
        </template>
      </t-form-item>

      <t-form-item label="Base URL">
        <t-input v-model="baseUrl" placeholder="https://…（留空使用官方默认地址）" />
        <template #help>自定义接口需兼容 OpenAI Chat Completions 协议；内网地址会被拒绝</template>
      </t-form-item>

      <t-form-item label="默认模型">
        <t-input v-model="defaultModel" placeholder="例如 deepseek-chat" />
      </t-form-item>
    </t-form>

    <!-- 探活结果：成功显示延迟，失败显示原因 -->
    <t-alert
      v-if="probeResult"
      :theme="probeResult.ok ? 'success' : 'error'"
      :title="probeText"
      class="probe"
    >
      <span v-if="!probeResult.ok && probeResult.errorCode" class="mono">
        错误码：{{ probeResult.errorCode }}
      </span>
    </t-alert>
    <t-alert v-else-if="failure" theme="error" :title="failure" class="probe" />

    <div class="actions">
      <t-button
        variant="outline"
        :loading="probing"
        :disabled="!card?.configured && !dirty"
        @click="test"
      >
        测试连接
      </t-button>
      <span class="spacer" />
      <t-button variant="outline" @click="close">取消</t-button>
      <t-button theme="primary" :loading="saving" @click="onSave">保存</t-button>
    </div>

    <p class="footnote">
      提示：「测试连接」测的是<strong>已保存</strong>的配置，
      所以表单一有改动会先保存再测 —— 否则测出来的是旧 Key 的结果。
    </p>
  </t-drawer>
</template>

<style scoped>
.hint {
  font-size: 13px;
  color: var(--td-text-secondary);
  line-height: 1.7;
  margin: 0 0 20px;
}

.eye {
  display: flex;
  padding: 4px;
  color: var(--td-text-placeholder);
  cursor: pointer;
}

.eye:hover {
  color: var(--td-text-primary);
}

.eye svg {
  width: 16px;
  height: 16px;
}

.probe {
  margin: 4px 0 16px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 8px;
}

.actions .spacer {
  flex: 1;
}

.footnote {
  margin-top: 16px;
  font-size: 12px;
  color: var(--td-text-secondary);
  line-height: 1.7;
}
</style>
