<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'

// 根组件
const authStore = useAuthStore()

onMounted(() => {
  // 有 token 时兜底拉取用户信息：
  // 1. 用户信息缺失（旧缓存/异常）时补全，避免 isAuthenticated=false 被踢回登录
  // 2. token 已失效时触发 logout 清理状态
  authStore.fetchCurrentUser()
})
</script>

<style lang="scss">
// 全局样式在 styles/global.scss 中定义
</style>
