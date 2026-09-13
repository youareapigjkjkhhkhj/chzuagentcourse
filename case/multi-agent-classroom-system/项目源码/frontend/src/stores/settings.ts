/**
 * 设置 store（P0 §7）：服务商 / 音色 / 生成参数 / 角色 / 能力清单。
 *
 * 一条纪律：**读操作吞异常，写操作抛异常**。
 * - 读（load*）失败时把原因记进 `lastError`，页面照样渲染骨架 ——
 *   后端没起来时前端更应该能显示「连接不上」，而不是白屏。
 * - 写（save / enable / probe）失败必须抛出去，因为用户正盯着按钮等结果，
 *   悄悄吞掉就等于让他以为保存成功了。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import * as api from '@/api'
import { ApiError } from '@/api/client'
import type {
  AgentRole,
  Capabilities,
  GenerationLimits,
  GenerationSettings,
  HealthInfo,
  ProviderCard,
  ProbeResult,
  SaveProviderPayload,
  VoiceSettings,
} from '@/types/api'

/** 把任何异常翻译成一句能显示给用户的话。 */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return '未知错误'
}

export const useSettingsStore = defineStore('settings', () => {
  const providers = ref<ProviderCard[]>([])
  const voice = ref<VoiceSettings | null>(null)
  const generation = ref<GenerationSettings | null>(null)
  const limits = ref<GenerationLimits | null>(null)
  const roles = ref<AgentRole[]>([])
  const capabilities = ref<Capabilities | null>(null)
  const health = ref<HealthInfo | null>(null)
  const loading = ref(false)
  const lastError = ref('')

  // --- 派生状态 ---

  /** 设置页的「模型服务商」列表：只列文本模型，语音走语音页。 */
  const llmProviders = computed(() => providers.value.filter((item) => item.kind === 'llm'))
  const enabledProvider = computed(() => providers.value.find((item) => item.enabled) ?? null)
  const teacherVoice = computed(
    () => voice.value?.voices.find((item) => item.id === voice.value?.teacherVoiceId) ?? null,
  )
  const teacher = computed(() => roles.value.find((item) => item.role === 'teacher') ?? null)
  const students = computed(() => roles.value.filter((item) => item.role === 'student'))

  /**
   * 材料功能开没开（P4-G3）：开关关着的部署里，工作台右侧那一栏整块不出现。
   *
   * **清单还没拉到时按「开着」算**：`/api/capabilities` 挂了不该让用户白白少
   * 一栏材料（那是把一次网络抖动变成功能缺失）；反过来最多是抽屉闪一下。
   */
  const materialEnabled = computed(() => capabilities.value?.materials?.enabled !== false)

  // --- 读 ---

  async function loadProviders(): Promise<void> {
    providers.value = (await api.fetchProviders()).items
  }

  async function loadVoice(): Promise<void> {
    voice.value = await api.fetchVoice()
  }

  async function loadGeneration(): Promise<void> {
    generation.value = await api.fetchGeneration()
  }

  async function loadRoles(): Promise<void> {
    roles.value = (await api.fetchRoles()).items
  }

  /** 能力清单同时带出滑杆边界（min/max 与后端校验同源）与各能力可用性。 */
  async function loadCapabilities(): Promise<void> {
    const data = await api.fetchCapabilities()
    capabilities.value = data
    limits.value = data.generation
  }

  async function loadHealth(): Promise<void> {
    health.value = await api.fetchHealth()
  }

  /**
   * 一次性把所有读接口拉齐。用 allSettled：
   * 某个接口挂了不该连累其余的 —— 设置页缺一块总好过整页空白。
   */
  async function loadAll(): Promise<void> {
    loading.value = true
    lastError.value = ''
    const results = await Promise.allSettled([
      loadProviders(),
      loadVoice(),
      loadGeneration(),
      loadRoles(),
      loadCapabilities(),
      loadHealth(),
    ])
    const failed = results.find((item) => item.status === 'rejected')
    if (failed) {
      lastError.value = describeError((failed as PromiseRejectedResult).reason)
    }
    loading.value = false
  }

  // --- 写（失败一律抛出，由调用页面提示） ---

  async function saveProvider(id: string, payload: SaveProviderPayload): Promise<ProviderCard> {
    const card = await api.saveProvider(id, payload)
    // 保存会改变注册表（新 Key 立刻生效），所以整列表重拉一次最省心
    await loadProviders()
    await loadCapabilities()
    return card
  }

  async function probe(id: string): Promise<ProbeResult> {
    const result = await api.probeProvider(id)
    await loadProviders() // 卡片要显示刚拿到的延迟
    return result
  }

  /** 启用是全局唯一的：启用后其余卡片的「已启用」标记都会消失。 */
  async function enable(id: string): Promise<void> {
    await api.enableProvider(id)
    await loadProviders()
    await loadHealth()
    await loadCapabilities()
  }

  async function saveVoice(patch: Partial<VoiceSettings>): Promise<void> {
    voice.value = await api.saveVoice(patch)
    await loadCapabilities()
  }

  async function saveGeneration(patch: Partial<GenerationSettings>): Promise<void> {
    generation.value = await api.saveGeneration(patch)
  }

  return {
    // state
    providers,
    voice,
    generation,
    limits,
    roles,
    capabilities,
    health,
    loading,
    lastError,
    // getters
    llmProviders,
    enabledProvider,
    teacherVoice,
    teacher,
    students,
    materialEnabled,
    // actions
    loadAll,
    loadProviders,
    loadVoice,
    loadGeneration,
    loadRoles,
    loadCapabilities,
    loadHealth,
    saveProvider,
    probe,
    enable,
    saveVoice,
    saveGeneration,
  }
})
