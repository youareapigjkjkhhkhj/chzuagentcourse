/**
 * vitest 全局准备。
 *
 * jsdom 缺的那几个浏览器 API 都在这里补上 —— 不补的话 TDesign 的
 * 组件（Sliders / Table 等都用了 ResizeObserver）会在挂载时直接抛异常，
 * 测试失败的原因看起来会像「组件写错了」，实际只是环境没有这个 API。
 */

import { afterEach, vi } from 'vitest'

if (!('matchMedia' in window)) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
}

if (!('ResizeObserver' in window)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(window, 'ResizeObserver', {
    writable: true,
    value: ResizeObserverStub,
  })
}

afterEach(() => {
  vi.clearAllMocks()
})
