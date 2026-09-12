/**
 * 「+ 章节」/「+ 页」的弹窗（P1-A3 的增章与增页）。
 *
 * 这个组件只干一件事：把「要加什么」问清楚，然后 `confirm` 出去。所以测试盯三件事：
 * 1. 两种模式问的东西不一样 —— 加章问章名 + 第一页，加页只问页标题，
 *    并且说得出这一页会落到哪一章
 * 2. **标题不能空着**：标题会写进写页的提示词，空标题生成出来就是一页空话，
 *    所以填上之前确认按钮是灰的，硬点也不出去
 * 3. 每次打开都重新起名，不把上一次输了一半的标题带过来
 *
 * 弹窗是 teleport 到 body 的（TDesign 默认 `attach="body"`），关掉也不销毁
 * （`v-show`），所以断言得在 `document` 上找，而且每个用例挂载的弹窗必须在下个
 * 用例前拆掉 —— 否则后一个用例会捞到前一个用例留在 body 里的那个按钮。
 */
import { DOMWrapper, enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import OutlineAddDialog from '@/components/workbench/OutlineAddDialog.vue'

enableAutoUnmount(afterEach)

function node<T extends Element>(selector: string): DOMWrapper<T> {
  const found = document.querySelector<T>(selector)
  if (!found) throw new Error(`弹窗里没有 ${selector}`)
  return new DOMWrapper(found)
}

/** 表单里的输入框，从上到下（加章两个：章名 + 第一页；加页一个）。 */
const inputs = () => Array.from(document.querySelectorAll<HTMLInputElement>('.t-dialog input'))

const confirmBtn = () => node<HTMLElement>('.t-dialog__confirm')
const headerText = () => document.querySelector('.t-dialog__header')?.textContent ?? ''
const hintText = () => document.querySelector('.t-dialog__body .hint')?.textContent ?? ''

interface DialogProps {
  visible: boolean
  mode: 'chapter' | 'page'
  context: string
  chapterCount: number
}

function mountDialog(props: Partial<DialogProps> = {}) {
  return mount(OutlineAddDialog, {
    props: {
      visible: true,
      mode: 'chapter',
      context: '「第一章 · 什么是机器学习」',
      chapterCount: 1,
      ...props,
    },
  })
}

describe('加章节 / 加页面的弹窗', () => {
  it('加页：只问页标题，并说清会落到哪一章末尾', async () => {
    const wrapper = mountDialog({ mode: 'page' })
    await flushPromises()

    expect(headerText()).toContain('新增页面')
    expect(inputs()).toHaveLength(1)
    expect(inputs()[0].value).toBe('新页面')
    expect(hintText()).toContain('「第一章 · 什么是机器学习」')
    expect(hintText()).toContain('末尾')

    await new DOMWrapper(inputs()[0]).setValue('梯度下降')
    await confirmBtn().trigger('click')
    await flushPromises()

    expect(wrapper.emitted('confirm')?.[0]?.[0]).toEqual({
      chapterTitle: '',
      pageTitle: '梯度下降',
    })
  })

  it('加章节：章名先给个默认的，两个标题都交出去（去掉首尾空格）', async () => {
    const wrapper = mountDialog({ mode: 'chapter', chapterCount: 2 })
    await flushPromises()

    expect(headerText()).toContain('新增章节')
    expect(inputs()).toHaveLength(2)
    expect(inputs()[0].value).toBe('第 3 章 · 新章节')
    // 「新章自带一页」这件事得写在明处，否则用户不知道为什么要填第二个框
    expect(hintText()).toContain('新章节自带一页正文')

    await new DOMWrapper(inputs()[0]).setValue('  第三章 · 神经网络  ')
    await new DOMWrapper(inputs()[1]).setValue(' 反向传播 ')
    await confirmBtn().trigger('click')
    await flushPromises()

    expect(wrapper.emitted('confirm')?.[0]?.[0]).toEqual({
      chapterTitle: '第三章 · 神经网络',
      pageTitle: '反向传播',
    })
  })

  it('页标题空着（或只有空格）就不让加：按钮是灰的，硬点也不出去', async () => {
    const wrapper = mountDialog({ mode: 'page' })
    await flushPromises()

    await new DOMWrapper(inputs()[0]).setValue('   ')
    await flushPromises()

    expect(confirmBtn().attributes('disabled')).toBeDefined()
    await confirmBtn().trigger('click')
    await flushPromises()
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })

  it('加章时第一页空着一样不让加 —— 空标题生成出来就是一页空话', async () => {
    const wrapper = mountDialog({ mode: 'chapter' })
    await flushPromises()

    await new DOMWrapper(inputs()[1]).setValue('')
    await flushPromises()

    expect(confirmBtn().attributes('disabled')).toBeDefined()
    await confirmBtn().trigger('click')
    await flushPromises()
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })

  it('关掉再打开重新起名，不带上一次输了一半的标题', async () => {
    const wrapper = mountDialog({ mode: 'page' })
    await flushPromises()
    await new DOMWrapper(inputs()[0]).setValue('上次输了一半的标题')
    await flushPromises()

    await wrapper.setProps({ visible: false })
    await flushPromises()
    await wrapper.setProps({ visible: true })
    await flushPromises()

    expect(inputs()[0].value).toBe('新页面')
  })
})
