<script setup lang="ts">
import { ref } from 'vue'

// 模板语法示例
const msg = 'Hello Vue 3 + TS'
const url = 'https://vuejs.org/images/logo.png'
const ok = ref(true)
const list = ref([1, 2, 3, 4, 5])
const count = ref(0)

function add() {
  count.value++
}

function toggle() {
  ok.value = !ok.value
}

function addItem() {
  list.value.push(list.value.length + 1)
}
</script>

<template>
  <div class="template-demo">
    <h2>05 · 模板语法</h2>

    <!-- 文本插值 -->
    <p>文本插值：{{ msg }}</p>

    <!-- 动态绑定属性 -->
    <p>动态绑定 img src：
      <img :src="url" alt="Vue Logo" style="height: 30px; vertical-align: middle;" />
    </p>

    <!-- v-if 条件渲染 -->
    <p>
      <button @click="toggle">切换显示</button>
      <span v-if="ok" style="color: green; margin-left: 8px;">条件成立，我显示了</span>
      <span v-else style="color: red; margin-left: 8px;">条件不成立，我显示了</span>
    </p>

    <!-- v-for 列表渲染 -->
    <p>
      <button @click="addItem">添加一项</button>
    </p>
    <ul>
      <li v-for="n in list" :key="n">第 {{ n }} 项</li>
    </ul>

    <!-- @ 事件绑定 -->
    <p>
      <button @click="add">点击次数：{{ count }}</button>
    </p>
  </div>
</template>

<style scoped>
.template-demo {
  border: 2px solid #3498db;
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0;
}
button {
  margin: 4px;
  padding: 4px 12px;
  cursor: pointer;
}
</style>
