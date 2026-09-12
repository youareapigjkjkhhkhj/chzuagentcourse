<script setup lang="ts">
import { useCounter } from './11-useCounter'

// 每次调用 useCounter 都拿到独立状态
const { count: countA, inc: incA, dec: decA, reset: resetA } = useCounter(0)
const { count: countB, inc: incB, dec: decB, reset: resetB } = useCounter(10)
</script>

<template>
  <div class="composable-demo">
    <h2>11 · 组合式函数 composables</h2>
    <p class="hint">composables 是普通函数，可复用状态 + 逻辑。下方两个计数器各自独立：</p>
    <div style="display: flex; gap: 24px;">
      <div>
        <h4>计数器 A (初始 0)</h4>
        <p>count = {{ countA }}</p>
        <button @click="incA">+1</button>
        <button @click="decA">-1</button>
        <button @click="resetA">重置</button>
      </div>
      <div>
        <h4>计数器 B (初始 10)</h4>
        <p>count = {{ countB }}</p>
        <button @click="incB">+1</button>
        <button @click="decB">-1</button>
        <button @click="resetB">重置</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.composable-demo {
  border: 2px solid #2ecc71;
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
