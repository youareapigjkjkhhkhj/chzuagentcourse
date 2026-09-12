<script setup lang="ts">
import { ref } from 'vue'
import ChildCard from './09-ChildCard.vue'

const parentCount = ref(0)
const childTitle = ref('来自父组件的标题')

function onUpdate(newVal: number) {
  parentCount.value = newVal
}
</script>

<template>
  <div class="props-demo">
    <h2>09 · 父子组件通信 props / emits</h2>
    <p>父组件 count = {{ parentCount }}</p>
    <ChildCard
      :title="childTitle"
      :count="parentCount"
      @update="onUpdate"
    />
    <p class="hint">父 → 子用 props；子 → 父用 emit；单向数据流</p>
  </div>
</template>

<style scoped>
.props-demo {
  border: 2px solid #1abc9c;
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0;
}
.hint {
  color: #888;
  font-size: 14px;
}
</style>
