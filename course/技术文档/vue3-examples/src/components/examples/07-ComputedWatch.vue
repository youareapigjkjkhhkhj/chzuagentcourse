<script setup lang="ts">
import { ref, computed, watch, watchEffect } from 'vue'

const count = ref(0)
const firstName = ref('张')
const lastName = ref('三')

// computed：派生只读数据
const double = computed(() => count.value * 2)
const fullName = computed(() => firstName.value + lastName.value)

// watch：侦听特定源
watch(count, (newVal, oldVal) => {
  console.log(`[watch] count: ${oldVal} -> ${newVal}`)
})

// watchEffect：自动追踪依赖
watchEffect(() => {
  console.log(`[watchEffect] 当前 count = ${count.value}, double = ${double.value}`)
})

function increment() {
  count.value++
}
</script>

<template>
  <div class="computed-demo">
    <h2>07 · 计算属性与侦听</h2>

    <h3>computed 派生状态</h3>
    <p>count = {{ count }}，double = {{ double }}</p>
    <button @click="increment">count++</button>
    <p class="hint">修改 count 后 double 自动更新，打开控制台查看 watch/watchEffect 日志</p>

    <h3>computed 组合姓名</h3>
    <p>姓：<input v-model="firstName" /> 名：<input v-model="lastName" /></p>
    <p>全名：{{ fullName }}</p>
  </div>
</template>

<style scoped>
.computed-demo {
  border: 2px solid #9b59b6;
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0;
}
button {
  margin: 4px;
  padding: 4px 12px;
  cursor: pointer;
}
input {
  margin: 0 4px;
  padding: 2px 8px;
}
.hint {
  color: #888;
  font-size: 14px;
}
</style>
