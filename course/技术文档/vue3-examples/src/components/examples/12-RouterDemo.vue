<script setup lang="ts">
</script>

<template>
  <div class="router-demo">
    <h2>12 · 路由 Vue Router</h2>
    <nav class="nav">
      <router-link to="/">首页</router-link>
      <router-link to="/about">关于</router-link>
    </nav>
    <div class="view-container">
      <router-view />
    </div>
    <p class="hint">点击导航链接切换页面，<code>&lt;router-view /&gt;</code> 渲染当前路由组件</p>
  </div>
</template>

<style scoped>
.router-demo {
  border: 2px solid #3498db;
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0;
}
.nav {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}
.nav a {
  padding: 6px 16px;
  background: #ecf0f1;
  border-radius: 4px;
  text-decoration: none;
  color: #333;
}
.nav a.router-link-active {
  background: #3498db;
  color: white;
}
.view-container {
  min-height: 80px;
  border: 1px solid #ddd;
  border-radius: 4px;
  padding: 8px;
}
.hint {
  color: #888;
  font-size: 14px;
  margin-top: 8px;
}
code {
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
