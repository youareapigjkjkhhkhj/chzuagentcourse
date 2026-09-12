<script setup lang="ts">
// 单文件组件 SFC 示例
// 一个 .vue 文件包含三段：<script setup>、<template>、<style scoped>
const count = 1
const title = '我的第一个 SFC'
</script>

<template>
  <div class="sfc-demo">
    <h2>04 · 单文件组件 SFC</h2>
    <h3>{{ title }}</h3>
    <p>count 的值：{{ count }}</p>
    <p class="hint">打开浏览器控制台查看 scoped 样式是否只作用于当前组件</p>
  </div>
</template>

<style scoped>
.sfc-demo {
  border: 2px solid #42b883;
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0;
}
h3 {
  color: #42b883;
}
.hint {
  color: #888;
  font-size: 14px;
}
</style>
