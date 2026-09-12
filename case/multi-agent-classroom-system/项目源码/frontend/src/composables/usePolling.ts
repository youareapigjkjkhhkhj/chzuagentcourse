/**
 * 一个可开关的定时轮询。
 *
 * 单独抽出来是因为「什么时候问、什么时候停」是最容易写错的一段：
 * 顺手 `setInterval` 的写法在组件卸载后还在跑，切课程时旧的那个也没人关。
 * 这里只管定时，不管问什么 —— 问什么由调用方给。
 */

import { onScopeDispose, ref, type Ref } from 'vue'

export interface Polling {
  start: () => void
  stop: () => void
  running: Ref<boolean>
}

export function usePolling(task: () => void, intervalMs: number): Polling {
  let timer: ReturnType<typeof setInterval> | null = null
  const running = ref(false)

  function stop(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
    running.value = false
  }

  function start(): void {
    if (timer !== null) return // 已经在跑了，再起一个只会让请求翻倍
    timer = setInterval(task, intervalMs)
    running.value = true
  }

  onScopeDispose(stop)

  return { start, stop, running }
}
