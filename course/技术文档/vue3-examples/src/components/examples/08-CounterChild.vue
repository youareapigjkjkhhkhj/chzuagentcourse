<script setup lang="ts">
import { ref } from 'vue'

// 子组件：Counter
const count = ref(0)
</script>

<template>
  <div class="counter-child">
    <button @click="count++">子组件计数：{{ count }}</button>
  </div>
</template>

<style scoped>
.counter-child {
  display: inline-block;
  margin: 4px;
}
button {
  padding: 4px 12px;
  cursor: pointer;
}
</style>
