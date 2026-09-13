<script setup lang="ts">
/**
 * 价目表（P5 §4.2）—— 设置页「成本」那一档的最后一截。
 *
 * 看板上的每一分钱都是**这张表乘出来的**，所以它得能在界面上维护：
 * 上游调价、或者某个模型压根没配单价（那时看板上的合计是少报的），
 * 用户得有地方改。
 *
 * 两条容易吃亏的地方：
 *
 * 1. **`llm` 那段是整段替换**（后端 `pricing.update` 的口径）。所以保存时
 *    要把表里**所有**模型一起发回去 —— 只发改过的那一个，其余会在库里消失，
 *    再回来看时它们的单价就成了 0，而界面完全不报错。
 * 2. **空/0 与「未配置」是两回事**（`priced`）。0 表示没配，看板会提示少报；
 *    界面这里要给一个「未配」的标记，而不是显示成 ¥0.0000 让人以为免费。
 */
import { computed, onMounted, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

import * as api from '@/api'
import { describeError } from '@/stores/settings'
import type { PricingRow, UsageModels } from '@/types/api'
import { USAGE_KIND_LABELS } from '@/utils/labels'

const data = ref<UsageModels | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')

/** 可编辑的草稿：`llm:模型名` 或 `语音链路:kind` → 单价。 */
const drafts = ref<Record<string, number>>({})

const llmRows = computed(() => (data.value?.pricing ?? []).filter((row) => row.kind === 'llm'))
const voiceRows = computed(() => (data.value?.pricing ?? []).filter((row) => row.kind !== 'llm'))

const llmKey = (row: PricingRow) => `llm:${row.model}`
const voiceKey = (row: PricingRow) => `${row.kind}:${row.kind}`

async function load(): Promise<void> {
  loading.value = true
  try {
    const payload = await api.fetchUsageModels()
    data.value = payload
    const next: Record<string, number> = {}
    for (const row of payload.pricing) {
      if (row.kind === 'llm') {
        next[`${llmKey(row)}:prompt`] = row.promptPer1k ?? 0
        next[`${llmKey(row)}:completion`] = row.completionPer1k ?? 0
      } else {
        next[voiceKey(row)] = row.unitPrice ?? 0
      }
    }
    drafts.value = next
    error.value = ''
  } catch {
    data.value = null
    error.value = '价目表读取失败，稍后再试'
  } finally {
    loading.value = false
  }
}

onMounted(load)

/** 改了没有：任意一格与读回来那份不同。 */
const dirty = computed(() => {
  const current = data.value
  if (!current) return false
  return current.pricing.some((row) =>
    row.kind === 'llm'
      ? drafts.value[`${llmKey(row)}:prompt`] !== (row.promptPer1k ?? 0) ||
        drafts.value[`${llmKey(row)}:completion`] !== (row.completionPer1k ?? 0)
      : drafts.value[voiceKey(row)] !== (row.unitPrice ?? 0),
  )
})

async function save(): Promise<void> {
  const current = data.value
  if (!current || !dirty.value) return
  saving.value = true
  try {
    // 见模块 docstring 第 1 条：llm 整段发回，一条都不能少
    const llm: Record<string, { promptPer1k: number; completionPer1k: number }> = {}
    for (const row of current.pricing) {
      if (row.kind !== 'llm') continue
      llm[row.model] = {
        promptPer1k: drafts.value[`${llmKey(row)}:prompt`] ?? 0,
        completionPer1k: drafts.value[`${llmKey(row)}:completion`] ?? 0,
      }
    }
    const voice: Record<string, Record<string, number>> = {}
    for (const row of current.pricing) {
      if (row.kind === 'llm' || !row.priceField) continue
      voice[row.kind] = { [row.priceField]: drafts.value[voiceKey(row)] ?? 0 }
    }
    await api.savePricing({ llm, ...voice })
    MessagePlugin.success('价目表已保存，看板上的估算值会按新单价重算')
    await load() // 回读一次：`priced` 那类标记由服务端算，本地不猜
  } catch (err) {
    MessagePlugin.error(describeError(err))
  } finally {
    saving.value = false
  }
}

/** 「哪几个模型现在真的在用」—— 价目表里配了一个没人用的模型是另一回事。 */
const activeModel = computed(
  () => data.value?.models.find((item) => item.active) ?? data.value?.models[0] ?? null,
)

function kindLabel(kind: string): string {
  return USAGE_KIND_LABELS[kind as keyof typeof USAGE_KIND_LABELS] ?? kind
}
</script>

<template>
  <section class="panel">
    <h3 class="panel__title">价目表</h3>
    <p class="panel__desc">
      看板上的金额按这里的单价估算（每千 token / 每千字符 / 每分钟）。
      单价填 0 表示<strong>未配置</strong> —— 这时看板上的合计是少报的。
    </p>

    <p v-if="loading && !data" class="pr-hint">读取中…</p>
    <p v-else-if="error" class="pr-hint is-error">{{ error }}</p>

    <template v-else-if="data">
      <p v-if="activeModel" class="pr-active">
        当前在用：<span class="mono">{{ activeModel.model || '（未指定模型）' }}</span>
        <span class="pr-active__by">（{{ activeModel.provider }}）</span>
      </p>

      <div v-if="llmRows.length" class="pr-block">
        <div class="pr-head"><span>模型</span><span>输入 / 千 token</span><span>输出 / 千 token</span></div>
        <div v-for="row in llmRows" :key="row.model" class="pr-row">
          <span class="pr-name mono">{{ row.model }}</span>
          <t-input-number
            v-model="drafts[`${llmKey(row)}:prompt`]"
            theme="column"
            size="small"
            :min="0"
            :step="0.5"
            :decimal-places="4"
          />
          <t-input-number
            v-model="drafts[`${llmKey(row)}:completion`]"
            theme="column"
            size="small"
            :min="0"
            :step="0.5"
            :decimal-places="4"
          />
          <t-tag v-if="!row.priced" class="pr-tag" size="small" variant="light" theme="warning">
            未配单价
          </t-tag>
        </div>
      </div>

      <div v-if="voiceRows.length" class="pr-block">
        <div class="pr-head"><span>语音链路</span><span>单价</span><span /></div>
        <div v-for="row in voiceRows" :key="row.kind" class="pr-row">
          <span class="pr-name">
            {{ kindLabel(row.kind) }}
            <span class="pr-unit">
              每 {{ row.unitSize }}{{ row.unitName === 'chars' ? ' 字符' : ' 秒' }}
            </span>
          </span>
          <t-input-number
            v-model="drafts[voiceKey(row)]"
            theme="column"
            size="small"
            :min="0"
            :step="0.1"
            :decimal-places="4"
          />
          <t-tag v-if="!row.priced" class="pr-tag" size="small" variant="light" theme="warning">
            未配单价
          </t-tag>
        </div>
      </div>

      <div class="pr-actions">
        <t-button theme="primary" size="small" :disabled="!dirty" :loading="saving" @click="save">
          保存价目表
        </t-button>
        <t-button size="small" variant="text" :disabled="!dirty" @click="load">还原</t-button>
      </div>

      <p class="pr-note">{{ data.note }}。改了单价只影响之后的估算，已经记下的账不回溯。</p>
    </template>
  </section>
</template>

<style scoped>
.pr-hint {
  font-size: 13px;
  color: var(--td-text-placeholder);
}

.pr-hint.is-error {
  color: var(--td-error-color);
}

.pr-active {
  margin: 4px 0 10px;
  font-size: 13px;
}

.pr-active__by {
  color: var(--td-text-placeholder);
  font-size: 12px;
}

.pr-block {
  margin-bottom: 12px;
}

.pr-head,
.pr-row {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) 130px 130px auto;
  gap: 10px;
  align-items: center;
}

.pr-head {
  padding-bottom: 6px;
  font-size: 12px;
  color: var(--td-text-placeholder);
  border-bottom: 1px solid var(--td-component-stroke);
}

.pr-row {
  padding: 6px 0;
  border-bottom: 1px dashed var(--td-component-stroke);
  font-size: 13px;
}

.pr-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pr-unit {
  display: block;
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.pr-tag {
  justify-self: start;
}

.pr-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}

.pr-note {
  margin-top: 10px;
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.mono {
  font-family: var(--td-font-mono);
}
</style>
