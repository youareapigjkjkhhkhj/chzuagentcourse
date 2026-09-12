<script setup lang="ts">
/**
 * 一张服务商卡片（P0-A3）。
 *
 * 状态位刻意分成三个，因为「已配置」不等于「能用」：
 * - 已启用   ：它是当前生效的那一家（全局唯一）
 * - 已配置   ：凭据齐了（`.env` 里给的也算）
 * - 不可用   ：有凭据但**现在调不动** —— 没有适配器，或适配器还没实现
 * 少了最后一条，P0 的语音卡片会一路显示绿色，用户带着它去上课才发现没声音。
 */
import { computed } from 'vue'

import type { ProviderCard } from '@/types/api'

const props = defineProps<{
  card: ProviderCard
  /** 探活中的卡片：按钮转圈，避免连点 */
  probing?: boolean
}>()

const emit = defineEmits<{
  configure: [card: ProviderCard]
  enable: [card: ProviderCard]
  test: [card: ProviderCard]
}>()

/** 两个字母的品牌缩写，取名字里的首字母/汉字 */
const initials = computed(() => {
  const name = props.card.name
  const ascii = name.replace(/[^A-Za-z]/g, '')
  return (ascii || name).slice(0, 2).toUpperCase()
})

const LOGO_COLORS: Record<string, string> = {
  deepseek: 'linear-gradient(135deg,#0052d9,#366ef4)',
  openai: 'linear-gradient(135deg,#10a37f,#1ac79b)',
  qwen: 'linear-gradient(135deg,#6a5fd0,#948be0)',
  kimi: 'linear-gradient(135deg,#333,#666)',
  custom: 'linear-gradient(135deg,#b98a5a,#d8b489)',
}

const logoStyle = computed(() => ({
  background: LOGO_COLORS[props.card.id] ?? LOGO_COLORS.custom,
}))

/** 卡片下方那行说明：模型 + 状态。没有任何一条时也要给出可读的兜底。 */
const meta = computed(() => {
  const model = props.card.defaultModel
  if (!props.card.configured) {
    const missing = props.card.missing.length ? `还缺：${props.card.missing.join('、')}` : '未配置'
    return model ? `${model} · ${missing}` : missing
  }
  if (!props.card.implemented) return `${model || '已配置'} · 适配器尚未接通`
  if (!props.card.available) return `${model || '已配置'} · 没有可用的适配器`
  return model ? `${model} · 默认用于课程生成与课堂对话` : '默认用于课程生成与课堂对话'
})

/** 只在探活成功过之后才显示延迟 —— 没测过就不编一个数字出来 */
const latencyText = computed(() =>
  typeof props.card.latencyMs === 'number' ? `延迟 ${props.card.latencyMs}ms` : '',
)
</script>

<template>
  <div class="provider" :class="{ 'is-enabled': card.enabled }">
    <span class="provider__logo" :style="logoStyle">{{ initials }}</span>

    <div class="provider__info">
      <div class="name">
        {{ card.name }}
        <t-tag v-if="card.enabled" theme="success" variant="light" size="small">已启用</t-tag>
        <t-tag v-else-if="!card.configured" variant="light" size="small">未配置</t-tag>
        <t-tag v-else-if="!card.available" theme="warning" variant="light" size="small">
          暂不可用
        </t-tag>
      </div>
      <div class="meta">{{ meta }}</div>
    </div>

    <div class="provider__actions">
      <t-tag v-if="latencyText" theme="primary" variant="light">{{ latencyText }}</t-tag>
      <t-button
        v-if="!card.enabled"
        size="small"
        variant="outline"
        :disabled="!card.configured"
        :title="card.configured ? '设为当前启用的服务商' : '先填好凭据再启用'"
        @click="emit('enable', card)"
      >
        启用
      </t-button>
      <t-button size="small" variant="outline" :loading="probing" @click="emit('test', card)">
        测试连接
      </t-button>
      <t-button size="small" theme="primary" variant="outline" @click="emit('configure', card)">
        配置
      </t-button>
    </div>
  </div>
</template>

<style scoped>
/* 版式取自 产品原型/settings.html 的 .provider */
.provider {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--td-component-border);
  border-radius: var(--td-radius-medium);
  margin-bottom: 12px;
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
}

.provider:hover {
  border-color: var(--td-brand-color);
  box-shadow: var(--td-shadow-1);
}

/* 当前生效的那家加一层品牌浅底 —— 原型没画，但「全局唯一」的启用态值得一眼看出来 */
.provider.is-enabled {
  background: var(--td-brand-color-light);
}

.provider__logo {
  width: 40px;
  height: 40px;
  border-radius: var(--td-radius-medium);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: #fff;
}

.provider__info {
  flex: 1;
  min-width: 0;
}

.provider__info .name {
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.provider__info .meta {
  font-size: 12px;
  color: var(--td-text-placeholder);
  margin-top: 3px;
}

.provider__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
</style>
