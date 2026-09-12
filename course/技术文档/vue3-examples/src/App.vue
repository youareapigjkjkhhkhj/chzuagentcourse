<script setup lang="ts">
// ========================================
// Vue 3 + TS 教学示例 - App.vue
// ========================================
// 教学时取消注释要演示的组件，注释掉其他组件
// ========================================

// --- 04. 单文件组件 SFC ---
import SFC from './components/examples/04-SFC.vue'

// --- 05. 模板语法 ---
import TemplateSyntax from './components/examples/05-TemplateSyntax.vue'

// --- 06. 响应式系统 ---
import ReactiveSystem from './components/examples/06-ReactiveSystem.vue'

// --- 07. 计算属性与侦听 ---
import ComputedWatch from './components/examples/07-ComputedWatch.vue'

// --- 08. 组件基础 ---
import ComponentBasics from './components/examples/08-ComponentBasics.vue'

// --- 09. 父子组件通信 ---
import PropsEmits from './components/examples/09-PropsEmits.vue'

// --- 10. 生命周期钩子 ---
import Lifecycle from './components/examples/10-Lifecycle.vue'

// --- 11. 组合式函数 ---
import Composables from './components/examples/11-Composables.vue'

// --- 12. 路由 ---
import RouterDemo from './components/examples/12-RouterDemo.vue'

// --- 13. 状态管理 Pinia ---
import PiniaDemo from './components/examples/13-PiniaDemo.vue'
</script>

<template>
  <div style="max-width: 800px; margin: 0 auto; padding: 20px; font-family: sans-serif;">
    <h1>Vue 3 + TypeScript 教学示例</h1>
    <p>取消注释对应组件即可演示各知识点，建议逐个演示。</p>

    <!-- 逐个取消注释来演示对应知识点 -->
    <SFC />
    <TemplateSyntax />
    <ReactiveSystem />
    <ComputedWatch />
    <ComponentBasics />
    <PropsEmits />
    <Lifecycle />
    <Composables />
    <!-- 路由和 Pinia 需要额外配置，见下方说明 -->
    <!-- <RouterDemo /> -->
    <!-- <PiniaDemo /> -->
  </div>
</template>
