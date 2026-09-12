<script setup lang="ts">
import { ref, onBeforeMount, onMounted, onBeforeUpdate, onUpdated, onBeforeUnmount, onUnmounted } from 'vue'

const logs = ref<string[]>([])
const count = ref(0)

function addLog(msg: string) {
  logs.value.push(`[${new Date().toLocaleTimeString()}] ${msg}`)
  console.log(msg)
}

onBeforeMount(() => addLog('onBeforeMount - 挂载前'))
onMounted(() => addLog('onMounted - 挂载完成，可访问 DOM'))
onBeforeUpdate(() => addLog('onBeforeUpdate - 数据变化，重新渲染前'))
onUpdated(() => addLog('onUpdated - 重新渲染完成'))
onBeforeUnmount(() => addLog('onBeforeUnmount - 卸载前'))
onUnmounted(() => addLog('onUnmounted - 卸载完成'))

// 模拟一个定时器，组件卸载时清理
let timer: ReturnType<typeof setInterval>
onMounted(() => {
  timer = setInterval(() => {
    // 空定时器，仅用于演示清理
  }, 1000)
})
onUnmounted(() => {
  clearInterval(timer)
  addLog('已清理定时器')
})
</script>

<template>
  <div class="lifecycle-demo">
    <h2>10 · 生命周期钩子</h2>
    <p>
      <button @click="count++">触发更新 (count: {{ count }})</button>
    </p>
    <p>打开浏览器控制台查看生命周期日志：</p>
    <ul>
      <li v-for="(log, i) in logs" :key="i">{{ log }}</li>
    </ul>
    <p class="hint">切换组件可见/不可见可观察 onMounted / onUnmounted</p>
  </div>
</template>

<style scoped>
.lifecycle-demo {
  border: 2px solid #e67e22;
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0;
}
button {
  cursor: pointer;
  padding: 4px 12px;
}
ul {
  max-height: 200px;
  overflow-y: auto;
  background: #f9f9f9;
  padding: 8px;
  border-radius: 4px;
}
.hint {
  color: #888;
  font-size: 14px;
}
</style>
