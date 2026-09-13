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

/**
 * jsdom 的媒体元素一个都没实现：`play()` / `pause()` 会往控制台丢一行
 * 「Not implemented」再返回 undefined。课堂页的播放器**本来就允许注入假的音频元素**
 * （见 `useNarrationPlayer` 的注释），但组件内部造的这个实例注入不进去 ——
 * 在这里补一个空实现，让那些用例的失败原因落在断言上，而不是落在一堆 stderr 上。
 *
 * 补的是**浏览器缺的东西**，不是替被测代码做事：`play()` 依旧不发声、不推进时间。
 */
const MEDIA_STUBS: [string, () => void][] = [
  ['play', () => {}],
  ['pause', () => {}],
  ['load', () => {}],
]

for (const [name, stub] of MEDIA_STUBS) {
  if (!window.HTMLMediaElement?.prototype) continue
  Object.defineProperty(window.HTMLMediaElement.prototype, name, {
    configurable: true,
    writable: true,
    value: stub,
  })
}

afterEach(() => {
  vi.clearAllMocks()
})
