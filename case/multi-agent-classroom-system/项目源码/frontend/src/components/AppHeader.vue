<script setup lang="ts">
/**
 * 顶栏（原型 `.app-header`，四页导航）。
 *
 * 刻意不用 TDesign 的 Menu：原型是「logo + 紧挨其后的导航 + 右侧头像」
 * 的自定义布局（导航 `flex:1` 靠左，不是居中），用 Menu 实现要反过来
 * 跟它的 DOM 结构较劲。导航只有四个链接，手写更短也更可控。
 *
 * 原型 index.html 右侧还有 GitHub / 通知两个图标按钮 —— 那是原型演示用的
 * 装饰，本项目没有这两个功能，所以不放「点了没反应」的按钮。
 */
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { useUserStore } from '@/stores/user'

const route = useRoute()
const user = useUserStore()

const NAV = [
  { name: 'index', to: '/', label: '首页' },
  { name: 'workbench', to: '/workbench', label: '工作台' },
  { name: 'classroom', to: '/classroom', label: '课堂演示' },
  { name: 'settings', to: '/settings', label: '设置' },
] as const

const activeName = computed(() => route.name)
</script>

<template>
  <header class="app-header">
    <RouterLink to="/" class="app-header__logo">
      <span class="logo-mark" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path
            d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H13l-4 4v-4H5.5A1.5 1.5 0 0 1 4 14.5v-9Z"
            fill="#fff"
          />
          <circle cx="9" cy="10" r="1.2" fill="#0052d9" />
          <circle cx="12.5" cy="10" r="1.2" fill="#0052d9" />
          <circle cx="16" cy="10" r="1.2" fill="#0052d9" />
        </svg>
      </span>
      <span class="logo-name">EduAgentX</span>
      <span class="logo-sub">多智能体互动课堂</span>
    </RouterLink>

    <nav class="app-header__nav">
      <RouterLink
        v-for="item in NAV"
        :key="item.name"
        :to="item.to"
        class="nav-item"
        :class="{ 'is-active': activeName === item.name }"
      >
        {{ item.label }}
      </RouterLink>
    </nav>

    <div class="app-header__right">
      <span class="t-avatar" :title="`${user.name}（本地用户）`">{{ user.initial }}</span>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 32px;
  height: 60px;
  padding: 0 32px;
  background: var(--td-bg-container);
  border-bottom: 1px solid var(--td-component-stroke);
}

.app-header__logo {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.logo-mark {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--td-brand-color);
  display: flex;
  align-items: center;
  justify-content: center;
}

.logo-name {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 0.2px;
  color: var(--td-text-primary);
}

.logo-sub {
  font-size: 12px;
  color: var(--td-text-placeholder);
  margin-left: 2px;
  transform: translateY(2px);
}

.app-header__nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
}

.nav-item {
  padding: 7px 14px;
  font-size: 14px;
  color: var(--td-text-secondary);
  border-radius: var(--td-radius-default);
  cursor: pointer;
  transition: all 0.2s;
}

.nav-item:hover {
  background: var(--td-bg-container-hover);
  color: var(--td-text-primary);
}

.nav-item.is-active {
  color: var(--td-brand-color);
  font-weight: 600;
  background: var(--td-brand-color-light);
}

.app-header__right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.t-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  flex-shrink: 0;
  background: linear-gradient(135deg, #0052d9, #618eff);
}
</style>
