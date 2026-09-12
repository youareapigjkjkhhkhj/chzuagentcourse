/**
 * 服务商卡片（P0-A3）。
 *
 * 卡片是设置页最容易被「配置好了」这句话骗过去的地方：
 * 有凭据但适配器还没实现时，它必须显示成「暂不可用」而不是一片绿。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ProviderCard from '@/components/ProviderCard.vue'
import type { ProviderCard as ProviderCardType } from '@/types/api'

function card(overrides: Partial<ProviderCardType> = {}): ProviderCardType {
  return {
    id: 'deepseek',
    name: 'DeepSeek',
    kind: 'llm',
    baseUrl: '',
    defaultModel: 'deepseek-chat',
    enabled: false,
    configured: true,
    available: true,
    implemented: true,
    maskedKey: 'sk-****4321',
    missing: [],
    latencyMs: null,
    extra: {},
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function render(overrides: Partial<ProviderCardType> = {}) {
  return mount(ProviderCard, { props: { card: card(overrides) } })
}

describe('状态渲染', () => {
  it('已启用 / 未配置 / 暂不可用 是三种不同的显示', () => {
    expect(render({ enabled: true }).text()).toContain('已启用')
    expect(render({ configured: false, available: false }).text()).toContain('未配置')
    expect(render({ configured: true, available: false, implemented: false }).text()).toContain(
      '暂不可用',
    )
  })

  it('未配置时说清还缺哪一栏，而不是只写「未配置」', () => {
    const wrapper = render({
      configured: false,
      available: false,
      missing: ['API Key', '接入地址'],
    })

    expect(wrapper.text()).toContain('还缺：API Key、接入地址')
  })

  it('凭据齐了但适配器是骨架：说明原因，不显示成可用', () => {
    const wrapper = render({ configured: true, available: false, implemented: false })

    expect(wrapper.text()).toContain('适配器尚未接通')
  })

  it('没探活过就不显示延迟数字（不编数据）', () => {
    expect(render().text()).not.toContain('延迟')
  })

  it('探活过就显示延迟', () => {
    expect(render({ latencyMs: 320 }).text()).toContain('延迟 320ms')
  })
})

describe('操作', () => {
  it('「配置」按钮把卡片抛给父组件', async () => {
    const wrapper = render()

    const button = wrapper.findAll('button').find((item) => item.text().includes('配置'))
    await button?.trigger('click')

    expect(wrapper.emitted('configure')).toHaveLength(1)
  })

  it('「测试连接」把卡片抛给父组件', async () => {
    const wrapper = render()

    const button = wrapper.findAll('button').find((item) => item.text().includes('测试连接'))
    await button?.trigger('click')

    expect(wrapper.emitted('test')).toHaveLength(1)
  })

  it('已启用的卡片不再显示「启用」按钮', () => {
    const wrapper = render({ enabled: true })

    expect(wrapper.findAll('button').some((item) => item.text().includes('启用'))).toBe(false)
  })

  it('没配好凭据时不能启用（先填 Key 再启用）', () => {
    const wrapper = render({ configured: false, available: false })
    const button = wrapper.findAll('button').find((item) => item.text().includes('启用'))

    expect(button?.attributes('disabled')).toBeDefined()
  })
})
