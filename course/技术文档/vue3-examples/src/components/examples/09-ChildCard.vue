<script setup lang="ts">
// 子组件：通过 defineProps 接收数据，通过 defineEmits 发送事件
const props = defineProps<{
  title: string
  count: number
}>()

const emit = defineEmits<{
  (e: 'update', value: number): void
}>()

function handleAdd() {
  emit('update', props.count + 1)
}
</script>

<template>
  <div class="child-card">
    <h4>{{ title }}</h4>
    <p>收到的 count：{{ count }}</p>
    <button @click="handleAdd">emit update (count + 1)</button>
  </div>
</template>

<style scoped>
.child-card {
  border: 1px dashed #3498db;
  border-radius: 6px;
  padding: 12px;
  margin: 8px 0;
}
button {
  cursor: pointer;
  padding: 4px 12px;
}
</style>
