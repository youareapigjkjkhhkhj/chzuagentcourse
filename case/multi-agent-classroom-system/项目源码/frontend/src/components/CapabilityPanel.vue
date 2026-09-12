<script setup lang="ts">
/**
 * 环境自检面板。
 *
 * P0 阶段最重要的一块信息：**此刻真的能用什么**。语音三件套要到 P2 才接通，
 * 用户第一眼就该看到，而不是等课堂里没声音才发现。
 *
 * 三态而不是两态：
 *   ready   就绪 —— 有凭据、有适配器、已实现
 *   offline 离线替身 —— 会走 mock，能演示但不是真模型
 *   blocked 不可用 —— 有凭据但适配器还没接通（P0 的语音三件套就是这样）
 * 「不可用」和「离线替身」必须分开说，否则用户不知道是该等版本还是该填 Key。
 */
import { computed } from 'vue'

import { useSettingsStore } from '@/stores/settings'
import type { ProviderKind } from '@/types/api'

const settings = useSettingsStore()

/** 四类能力的展示名与顺序。 */
const KIND_LABELS: Record<ProviderKind, string> = {
  llm: '文本生成',
  tts: '语音合成',
  asr: '语音识别',
  realtime: '实时语音',
}

interface CapabilityRow {
  kind: ProviderKind
  label: string
  status: 'ready' | 'offline' | 'blocked'
  provider: string
  reason: string
}

const rows = computed<CapabilityRow[]>(() => {
  const caps = settings.capabilities?.capabilities
  if (!caps) return []
  return (Object.keys(KIND_LABELS) as ProviderKind[]).map((kind) => {
    const info = caps[kind]
    return {
      kind,
      label: KIND_LABELS[kind],
      status: info.available ? 'ready' : info.offline ? 'offline' : 'blocked',
      provider: info.provider,
      reason: info.reason,
    }
  })
})

const STATUS_TEXT: Record<CapabilityRow['status'], string> = {
  ready: '就绪',
  offline: '离线替身',
  blocked: '不可用',
}

const STATUS_THEME: Record<CapabilityRow['status'], 'success' | 'warning' | 'danger'> = {
  ready: 'success',
  offline: 'warning',
  blocked: 'danger',
}

// 表格插槽的行数据是 any（TDesign 插槽没有泛型），用两个带类型的取值函数
// 把类型收回来 —— 表里少一个键时编译期就能发现
function statusText(row: CapabilityRow): string {
  return STATUS_TEXT[row.status]
}

function statusTheme(row: CapabilityRow): 'success' | 'warning' | 'danger' {
  return STATUS_THEME[row.status]
}

const COLUMNS = [
  { colKey: 'label', title: '能力', width: 120 },
  { colKey: 'provider', title: '服务商', width: 140 },
  { colKey: 'status', title: '状态', width: 120 },
  { colKey: 'reason', title: '说明' },
]
</script>

<template>
  <div class="panel">
    <h3 class="panel__title">环境自检</h3>
    <p class="panel__desc">
      这里显示的是<strong>此刻真实可用</strong>的能力，不是「已配置」的勾。
      被标成「不可用」的入口现在点下去会失败，原因写在右侧。
    </p>

    <t-table
      v-if="rows.length"
      :data="rows"
      :columns="COLUMNS"
      row-key="kind"
      size="small"
      :bordered="false"
    >
      <template #provider="{ row }">
        <span class="mono">{{ row.provider }}</span>
      </template>
      <template #status="{ row }">
        <t-tag :theme="statusTheme(row)" variant="light">{{ statusText(row) }}</t-tag>
      </template>
      <template #reason="{ row }">
        <span class="muted">{{ row.reason || '—' }}</span>
      </template>
    </t-table>
    <t-loading v-else :loading="settings.loading" text="正在读取环境状态…" />
  </div>
</template>

<style scoped>
/* 表格自己会画边框，这里的 muted/mono 只管文字 */
.muted {
  color: var(--td-text-secondary);
}

.mono {
  font-family: var(--td-font-mono);
}
</style>
