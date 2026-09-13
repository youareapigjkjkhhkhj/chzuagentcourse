/**
 * 溯源徽标与页面上的出处行（P4-A6 / P4-A13）。
 *
 * 两条验收在这一处交汇：
 *
 * 1. **点得动**：徽标上写「第 12 页」，点一下把这条出处交给工作台去开抽屉。
 * 2. **删了就说删了**：材料被删之后徽标要变成失效态 —— 这是个界面上的承诺
 *    （删之前那句确认框就是这么说的），所以它得当场兑现，而不是等用户点开
 *    发现是个空抽屉。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PageSlide from '@/components/workbench/PageSlide.vue'
import type { CoursePageItem, SlideSource } from '@/types/api'

const SOURCE: SlideSource = {
  materialId: 'f1',
  chunkId: 'k9',
  pageNo: 12,
  sectionPath: '第三章 · 神经网络',
  quote: '反向传播的链式求导……',
  score: 0.82,
}

function makePage(sources: SlideSource[]): CoursePageItem {
  return {
    id: 'p1',
    courseId: 'c1',
    chapterNo: 3,
    pageNo: 5,
    kind: 'concept',
    title: '反向传播',
    status: 'ready',
    rev: 2,
    dsl: { title: '反向传播', bullets: [{ text: '链式法则' }], sources },
  }
}

function mountSlide(missing: string[] = [], sources: SlideSource[] = [SOURCE]) {
  const wrapper = mount(PageSlide, {
    props: {
      page: makePage(sources),
      courseTitle: '机器学习入门',
      pageCount: 12,
      missingSources: missing,
    },
  })
  return wrapper
}

describe('出处徽标', () => {
  it('徽标写的是材料里的页码，点一下把这条出处交出去', async () => {
    const wrapper = mountSlide()

    const chip = wrapper.find('.src__chip')
    expect(chip.text()).toContain('第 12 页')
    expect(chip.text()).not.toContain('已失效')

    await chip.trigger('click')
    expect(wrapper.emitted('openSource')?.[0]).toEqual([SOURCE])
  })

  it('整份材料被删：这一页所有引用它的徽标一起变失效态（P4-A13）', () => {
    // 抽屉按材料那一级报「没了」—— 它也不知道这一页引的是哪几段
    const wrapper = mountSlide(['f1'])

    expect(wrapper.find('.src').classes()).toContain('is-missing')
    expect(wrapper.find('.src__chip').text()).toContain('已失效')
  })

  it('删的是别一份材料：这一条的徽标照旧点得动', () => {
    const wrapper = mountSlide(['f2'])

    expect(wrapper.find('.src').classes()).not.toContain('is-missing')
    expect(wrapper.find('.src__chip').text()).not.toContain('已失效')
  })

  it('只挂 sourceMissing 的页面标「出处对不上」，与「材料删了」是两回事', () => {
    const wrapper = mountSlide([], [])
    const page = makePage([])
    page.dsl = { ...page.dsl, sourceMissing: true }
    const flagged = mount(PageSlide, {
      props: { page, courseTitle: '机器学习入门', pageCount: 12 },
    })

    expect(wrapper.find('.slide-flags').exists()).toBe(false)
    expect(flagged.find('.slide-flags').text()).toContain('出处对不上')
    expect(flagged.find('.src').exists()).toBe(false) // 没核对上的引文根本不画徽标
  })
})

describe('材料没写到的部分（P4-A8）', () => {
  it('gaps 说出来了，而不是让它编一段', () => {
    const page = makePage([SOURCE])
    page.dsl = { ...page.dsl, gaps: ['材料未涉及卷积神经网络'] }
    const wrapper = mount(PageSlide, {
      props: { page, courseTitle: '机器学习入门', pageCount: 12 },
    })

    expect(wrapper.find('.slide-flags').text()).toContain('材料没写')
    expect(wrapper.find('.slide-flags').text()).toContain('卷积神经网络')
  })
})

describe('课堂舞台那一份', () => {
  it('不带徽标：那边点击跳转没有落点（抽屉属于工作台）', () => {
    const wrapper = mount(PageSlide, {
      props: { page: makePage([SOURCE]), courseTitle: '机器学习入门', pageCount: 12, variant: 'classroom' },
    })

    expect(wrapper.find('.src').exists()).toBe(false)
    // 但要点还在 —— 课堂那一份画的是同一页内容
    expect(wrapper.find('.slide-title').text()).toContain('反向传播')
  })
})
