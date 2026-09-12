<script setup lang="ts">
import { useCounterStore } from '../../stores/counter'

const store = useCounterStore()
</script>

<template>
  <div class="pinia-demo">
    <h2>13 · 状态管理 Pinia</h2>
    <p>store.count = {{ store.count }}，store.double = {{ store.double }}</p>
    <button @click="store.increment">+</button>
    <button @click="store.decrement">-</button>
    <button @click="store.reset">重置</button>
    <p class="hint">Pinia 是跨组件共享全局状态的仓库，比 Vuex 更简洁</p>
  </div>
</template>

<style scoped>
.pinia-demo {
  border: 2px solid #e74c3c;
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0;
}
button {
  cursor: pointer;
  padding: 4px 12px;
  margin: 2px;
}
.hint {
  color: #888;
  font-size: 14px;
}
</style>
