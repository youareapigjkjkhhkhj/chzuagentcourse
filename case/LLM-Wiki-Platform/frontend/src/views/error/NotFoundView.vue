<template>
  <div class="not-found">
    <div class="content">
      <h1>404</h1>
      <p>抱歉，您访问的页面不存在</p>
      <el-button type="primary" @click="router.push('/')">
        返回首页
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.not-found {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background: $gradient-dark;
}

.content {
  text-align: center;
  color: $text-primary;
  
  h1 {
    font-size: 120px;
    margin: 0 0 20px 0;
    font-weight: bold;
    background: $gradient-primary;
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  
  p {
    font-size: 20px;
    margin: 0 0 30px 0;
    color: $text-secondary;
  }
}
</style>