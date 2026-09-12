<script setup lang="ts">
import AppHeader from '@/components/AppHeader.vue'
</script>

<template>
  <AppHeader />
  <main>
    <RouterView />
  </main>
</template>

<style scoped>
/* 60px 是原型 .app-header 的高度（工作台/课堂用 calc(100vh - 60px) 撑满一屏） */
main {
  min-height: calc(100vh - 60px);
}
</style>
