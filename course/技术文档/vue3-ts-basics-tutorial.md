# Vue 3 基础教程（TypeScript 版）

> 组合式 API 与 TypeScript 从入门到实战 · 教育版入门讲义
> 适用环境：Vue 3 + TypeScript + Vite

本教程与配套 PPT《Vue 3 基础教程（TS 版）》内容一一对应，共 15 节。所有示例代码均可直接复制到本地项目运行。

---

## 目录

1. [什么是 Vue 3](#02)
2. [环境搭建](#03)
3. [项目结构](#04)
4. [单文件组件 SFC](#05)
5. [模板语法](#06)
6. [响应式系统](#07)
7. [计算属性与侦听 computed / watch](#08)
8. [组件基础](#09)
9. [父子组件通信 props / emits](#10)
10. [生命周期钩子](#11)
11. [组合式函数 composables](#12)
12. [路由 Vue Router](#13)
13. [状态管理 Pinia](#14)
14. [学习路径与总结](#15)

---

## 01 · 封面概览 <a id="01"></a>

- **主题**：Vue 3 基础教程（TypeScript 版）
- **主线**：组合式 API（Composition API）与 TypeScript 的协同使用
- **关键词**：响应式 · 组件 · Composition API · 路由 · Pinia 状态管理
- **技术栈**：Vue 3 + TypeScript + Vite

本教程采用「先建立心智模型，再动手写代码」的节奏，从单文件组件、响应式系统讲起，逐步过渡到组件通信、路由与状态管理，最后给出工程化学习路径。

---

## 02 · 什么是 Vue 3？ <a id="02"></a>

Vue 是**渐进式** JavaScript 框架；Vue 3 默认使用**组合式 API**，并对 TypeScript 提供**一流支持**。先建立四个核心心智模型：

| 概念 | 说明 |
| --- | --- |
| 🪜 渐进式框架 | 可逐步采用，从一小段到完整应用；不强制整套框架，按需引入 |
| 🔁 响应式系统 | 数据变化自动驱动视图更新；基于 `Proxy` 的细粒度追踪 |
| 🧩 组件化 | 用可复用组件拼装界面；单文件组件 `.vue` 组织代码 |
| 🟦 TypeScript 友好 | 官方提供完整类型定义；组合式 API 类型推导优秀 |

> **渐进式**意味着你可以在现有页面里只引入 Vue 的一部分（例如只做数据绑定），也可以逐步演进为完整的单页应用。

---

## 03 · 环境搭建 <a id="03"></a>

### 前置条件

- 已安装 Node.js（建议 18+，含 `npm`）
- 一个现代终端（PowerShell / Terminal / Git Bash 均可）

### 四步上手

```bash
# 1. 确认 Node 版本
node -v

# 2. 用官方脚手架创建 Vue + TS 项目
npm create vite@latest frontend -- --template vue-ts

# 3. 进入目录并安装依赖
cd frontend
npm install

# 4. 启动开发服务器
npm run dev
```

启动成功后终端会输出本地地址（默认 `http://localhost:5173`），在浏览器打开即可看到初始页面。

> 如果你更偏好交互式创建，可直接运行 `npm create vite@latest` 后按提示选择 `Vue` → `TypeScript`。

---

## 04 · 项目结构 <a id="03"></a>

一个 Vite + Vue + TS 项目的关键目录如下：

```
my-app/
├─ index.html              # 应用入口 HTML
├─ vite.config.ts          # Vite 配置
├─ tsconfig.json           # TypeScript 配置
└─ src/
   ├─ main.ts              # 应用启动入口
   ├─ App.vue              # 根组件
   ├─ components/          # 业务组件目录
   └─ assets/              # 静态资源
```

### `src/main.ts` — 应用启动入口

```ts
import { createApp } from 'vue'
import App from './App.vue'

createApp(App).mount('#app')
```

### `src/App.vue` — 根组件

```vue
<script setup lang="ts">
import HelloWorld from './components/HelloWorld.vue'
</script>

<template>
  <HelloWorld msg="Vue 3 + TS" />
</template>
```

`main.ts` 负责把根组件挂载到 `#app`；`App.vue` 是组件树的起点，其余组件在它之下层层嵌套。

---

## 05 · 单文件组件 SFC <a id="05"></a>

Vue 用**单文件组件（SFC，`.vue` 文件）**组织代码，一个文件包含三段：

```vue
<script setup lang="ts">
// 逻辑层：用 TS 写状态与方法
const count = 1
</script>

<template>
  <!-- 视图层：模板 -->
  <p>{{ count }}</p>
</template>

<style scoped>
/* 样式层：scoped 表示仅作用于当前组件 */
p {
  color: #42b883;
}
</style>
```

| 段落 | 作用 | 要点 |
| --- | --- | --- |
| `<template>` | 视图层 | 声明式描述页面结构 |
| `<script setup lang="ts">` | 逻辑层 | `setup` 编译时语法，`lang="ts"` 启用 TS |
| `<style scoped>` | 样式层 | `scoped` 让样式只作用于当前组件 |

> `<script setup>` 是组合式 API 的推荐写法：顶层绑定自动暴露给模板，无需 `return`。

---

## 06 · 模板语法 <a id="06"></a>

模板中用少量指令把数据与视图连接起来：

| 语法 | 含义 | 示例 |
| --- | --- | --- |
| `{{ }}` | 文本插值 | `<p>{{ msg }}</p>` |
| `:` / `v-bind` | 动态绑定属性 | `<img :src="url" />` |
| `v-if` | 条件渲染 | `<p v-if="ok">显示</p>` |
| `v-for` | 列表渲染 | `<li v-for="n in list" :key="n">{{ n }}</li>` |
| `@` / `v-on` | 事件绑定 | `<button @click="add">+</button>` |

```vue
<script setup lang="ts">
const msg = 'Hello Vue'
const url = '/logo.png'
const ok = true
const list = [1, 2, 3]
const add = () => console.log('clicked')
</script>

<template>
  <p>{{ msg }}</p>
  <img :src="url" />
  <p v-if="ok">条件成立才渲染</p>
  <ul>
    <li v-for="n in list" :key="n">{{ n }}</li>
  </ul>
  <button @click="add">+</button>
</template>
```

> 列表渲染务必用 `:key` 提供稳定标识，帮助 Vue 高效复用 DOM 节点。

---

## 07 · 响应式系统 <a id="07"></a>

Vue 3 用 `ref` 与 `reactive` 让数据「响应式」——数据变化自动更新视图。

```ts
import { ref, reactive } from 'vue'

// 基本类型 / 单值用 ref，访问需 .value
const count = ref<number>(0)
count.value++

// 对象 / 多字段用 reactive，直接访问属性
const state = reactive<{ name: string; age: number }>({
  name: 'Vue',
  age: 3,
})
state.age++
```

| API | 适用 | 访问方式 |
| --- | --- | --- |
| `ref` | 基本类型、单值，也可包对象 | `x.value` |
| `reactive` | 对象、多字段集合 | `obj.key` |

```vue
<script setup lang="ts">
import { ref } from 'vue'

const count = ref<number>(0)
</script>

<template>
  <p>{{ count }}</p>
  <button @click="count++">+1</button>
</template>
```

> TypeScript 标注：`ref<number>(0)` 明确告诉编译器 `count` 是 `number` 类型，获得完整类型推导与补全。

---

## 08 · 计算属性与侦听 <a id="08"></a>

### `computed` — 派生状态

基于响应式数据计算出新值，只有依赖变化时才重新计算。

```ts
import { ref, computed } from 'vue'

const count = ref(1)
const double = computed(() => count.value * 2)
```

### `watch` — 侦听特定源

观察一个或多个来源，在其变化时执行副作用（如请求、日志）。

```ts
import { ref, watch } from 'vue'

const count = ref(0)
watch(count, (newVal, oldVal) => {
  console.log(`count: ${oldVal} -> ${newVal}`)
})
```

### `watchEffect` — 自动追踪

立即执行并自动收集依赖，依赖变化即重新运行。

```ts
import { ref, watchEffect } from 'vue'

const count = ref(0)
watchEffect(() => {
  console.log(`当前 count = ${count.value}`)
})
```

| API | 触发时机 | 典型用途 |
| --- | --- | --- |
| `computed` | 依赖变化时重算，带缓存 | 派生只读数据 |
| `watch` | 指定源变化 | 副作用、异步 |
| `watchEffect` | 立即执行 + 依赖变化 | 自动追踪的副作用 |

---

## 09 · 组件基础 <a id="09"></a>

组件是可复用的 `.vue` 文件；在父组件中 `import` 后直接在模板使用。

```vue
<!-- components/Counter.vue -->
<script setup lang="ts">
const count = ref(0)
</script>

<template>
  <button @click="count++">{{ count }}</button>
</template>
```

```vue
<!-- 父组件 -->
<script setup lang="ts">
import Counter from './components/Counter.vue'
</script>

<template>
  <Counter />
</template>
```

要点：

- **组件 = `.vue` 文件**：把界面拆成独立、可复用单元
- **import 即注册**：无需额外 `components` 配置
- **标签名 = 文件名**：推荐 PascalCase，如 `<Counter />`
- **向下传数据**：通过属性把数据传给子组件
- 组件越大越该拆分

---

## 10 · 父子组件通信 props / emits <a id="10"></a>

- 父 → 子：用 **props** 传数据
- 子 → 父：用 **emits** 发事件

在 `<script setup>` 中，`defineProps` 与 `defineEmits` 是**编译器宏**，无需 `import` 即可使用。

```vue
<script setup lang="ts">
// 父 → 子：声明接收的属性及其类型
const props = defineProps<{
  title: string
  count: number
}>()

// 子 → 父：声明可触发的事件
const emit = defineEmits<{
  (e: 'change', value: number): void
}>()

function onClick() {
  emit('change', props.count + 1)
}
</script>
```

父组件监听：

```vue
<template>
  <Child :title="t" :count="n" @change="onChange" />
</template>
```

| 宏 | 作用 | 注意 |
| --- | --- | --- |
| `defineProps` | 接收父组件数据，类型即约束 | 单向数据流，子组件不应直接改 props |
| `defineEmits` | 向父组件发送事件 | 事件名与参数均受 TS 检查 |

> **单向数据流**：props 只能从父流向子；子组件想通知父组件改变，应通过 `emit` 让父组件自己改。

---

## 11 · 生命周期钩子 <a id="11"></a>

组件从创建到销毁，在关键节点注册回调。组合式 API 中钩子以 `onXxx()` 形式在 `setup` 内直接调用，组件卸载时自动清理。

```vue
<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

onMounted(() => {
  console.log('组件已挂载')
})

onUnmounted(() => {
  console.log('组件已卸载')
})
</script>
```

| 钩子 | 触发时机 |
| --- | --- |
| `onBeforeMount` | 组件挂载前 |
| `onMounted` | 挂载完成，可访问 DOM / 发起请求 |
| `onBeforeUpdate` | 数据变化、重新渲染前 |
| `onUpdated` | 重新渲染完成 |
| `onBeforeUnmount` | 卸载前，清理定时器 / 监听 |
| `onUnmounted` | 卸载完成 |

> 在 `onMounted` 中发起数据请求、在 `onUnmounted` 中清理定时器，是避免内存泄漏的常见组合。

---

## 12 · 组合式函数 composables <a id="12"></a>

把「状态 + 逻辑」抽成可复用的函数，约定以 **`use`** 开头；内部可自由使用 `ref` / `reactive` / 生命周期钩子，被多个组件共享。

```ts
// composables/useCounter.ts
import { ref } from 'vue'

export function useCounter(init = 0) {
  const count = ref(init)
  const inc = () => count.value++
  const dec = () => count.value--
  return { count, inc, dec }
}
```

在组件中使用：

```vue
<script setup lang="ts">
import { useCounter } from './useCounter'

const { count, inc, dec } = useCounter(10)
</script>

<template>
  <p>{{ count }}</p>
  <button @click="inc">+</button>
  <button @click="dec">-</button>
</template>
```

| 优势 | 说明 |
| --- | --- |
| 复用 | 每个调用方拿到独立状态，互不影响 |
| 可测 | 逻辑是普通函数，易于单元测试 |
| 整洁 | 把复杂逻辑移出组件，组件只管视图 |

> 逻辑复用 = 函数复用；composables 是 Vue 3 推荐的代码组织方式。

---

## 13 · 路由 Vue Router <a id="13"></a>

用 URL 映射不同页面组件。

```ts
// router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import Home from './views/Home.vue'

const routes = [
  { path: '/', component: Home },
  { path: '/about', component: () => import('./views/About.vue') },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
```

在 `main.ts` 中注册：

```ts
import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'

createApp(App).use(router).mount('#app')
```

在根组件渲染出口与导航：

```vue
<template>
  <nav>
    <router-link to="/">首页</router-link>
    <router-link to="/about">关于</router-link>
  </nav>
  <router-view />
</template>
```

| 概念 | 作用 |
| --- | --- |
| `routes` 数组 | `path` 与 `component` 的映射 |
| `router-view` | 渲染当前路由匹配的组件 |
| `router-link` | 声明式导航（生成 `<a>`） |
| `() => import()` | 路由懒加载，按需加载组件 |

---

## 14 · 状态管理 Pinia <a id="14"></a>

跨组件共享的全局数据仓库，比 Vuex 更简洁。

```ts
// stores/counter.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useCounterStore = defineStore('counter', () => {
  const count = ref(0)
  const double = computed(() => count.value * 2)
  function increment() {
    count.value++
  }
  return { count, double, increment }
})
```

组件内使用：

```vue
<script setup lang="ts">
import { useCounterStore } from './stores/counter'

const store = useCounterStore()
</script>

<template>
  <p>{{ store.count }} / {{ store.double }}</p>
  <button @click="store.increment">+</button>
</template>
```

在 `main.ts` 中先安装 Pinia：

```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'

createApp(App).use(createPinia()).mount('#app')
```

| 概念 | 作用 |
| --- | --- |
| `defineStore` | 创建带唯一 `id` 的 store |
| `state` | 用 `ref` / `reactive` 定义状态 |
| `getters` | 用 `computed` 派生只读数据 |
| `actions` | 定义修改状态的方法 |
| `useStore()` | 组件内读取并自动响应 |

---

## 15 · 学习路径与总结 <a id="15"></a>

从语法到工程化，构建 Vue 3 + TypeScript 的完整认知闭环：

| 阶段 | 主题 | 关键点 |
| --- | --- | --- |
| 01 | 基础语法 | SFC 结构、模板指令、插值表达式 |
| 02 | 响应式 | `ref` / `reactive` / `computed` / `watch` |
| 03 | 组件通信 | `props` / `emits` 父子传值 |
| 04 | 工程化 | Vue Router 路由 + Pinia 状态管理 |
| 05 | 复用进阶 | `composables` 组合式函数抽离 |

**建议下一步**：

1. 完整跑通本教程的每一个示例，不要只读不写。
2. 用前面学到的知识，动手写一个小型项目（如待办列表 + 路由 + Pinia）。
3. 阅读官方文档：[vuejs.org](https://vuejs.org) 与 [pinia.vuejs.org](https://pinia.vuejs.org)、[router.vuejs.org](https://router.vuejs.org)。

> 动手写一个完整项目，是巩固这些概念最好的方式 🚀

