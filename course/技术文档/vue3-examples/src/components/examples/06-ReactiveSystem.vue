<script setup lang="ts">
import { ref, reactive } from 'vue'

// ref：基本类型 / 单值
const count = ref<number>(0)
function increment() {
  count.value++
}

// reactive：对象 / 多字段
const user = reactive<{ name: string; age: number }>({
  name: 'Vue',
  age: 3,
})
function growUp() {
  user.age++
}
</script>

<template>
  <div class="reactive-demo">
    <h2>06 · 响应式系统</h2>

    <h3>ref 示例</h3>
    <p>count = {{ count }}</p>
    <button @click="increment">count++</button>
    <p class="hint">在 &lt;script&gt; 中通过 count.value 修改，在模板中直接用 {{ count }}</p>

    <h3>reactive 示例</h3>
    <p>{{ user.name }} 的年龄 = {{ user.age }}</p>
    <button @click="growUp">age++</button>
    <p class="hint">reactive 对象直接访问属性，无需 .value</p>
  </div>
</template>

<style scoped>
.reactive-demo {
  border: 2px solid #e74c3c;
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0;
}
button {
  margin: 4px;
  padding: 4px 12px;
  cursor: pointer;
}
.hint {
  color: #888;
  font-size: 14px;
}
</style>
