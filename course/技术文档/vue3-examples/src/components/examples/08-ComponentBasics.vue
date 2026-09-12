<script setup lang="ts">
import Counter from './08-CounterChild.vue'
</script>

<template>
  <div class="component-demo">
    <h2>08 · 组件基础</h2>
    <p>下方是独立的子组件 <code>&lt;Counter /&gt;</code>，点击按钮各自维护独立状态：</p>
    <Counter />
    <Counter />
    <Counter />
    <p class="hint">import 即注册，无需额外 components 配置；标签名 = 文件名（PascalCase）</p>
  </div>
</template>

<style scoped>
.component-demo {
  border: 2px solid #f39c12;
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0;
}
code {
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 4px;
}
.hint {
  color: #888;
  font-size: 14px;
}
</style>
