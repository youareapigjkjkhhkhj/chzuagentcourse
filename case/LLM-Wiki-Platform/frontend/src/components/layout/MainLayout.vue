<template>
  <div class="main-layout">
    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ collapsed: isCollapse }">
      <div class="sidebar-header">
        <div class="logo-wrapper">
          <div class="logo-icon">
            <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect width="40" height="40" rx="10" fill="url(#sidebar-logo-gradient)"/>
              <path d="M12 14h16v2H12v-2zm0 4h16v2H12v-2zm0 4h10v2H12v-2z" fill="white"/>
              <defs>
                <linearGradient id="sidebar-logo-gradient" x1="0" y1="0" x2="40" y2="40">
                  <stop stop-color="#0ea5e9"/>
                  <stop offset="1" stop-color="#6366f1"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
          <transition name="fade">
            <span v-if="!isCollapse" class="logo-text">LLM Wiki</span>
          </transition>
        </div>
      </div>
      
      <nav class="sidebar-nav">
        <router-link 
          v-for="item in menuItems" 
          :key="item.path"
          :to="item.path" 
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <div class="nav-icon">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>
          <transition name="fade">
            <span v-if="!isCollapse" class="nav-text">{{ item.label }}</span>
          </transition>
          <transition name="fade">
            <span v-if="!isCollapse && item.badge" class="nav-badge">{{ item.badge }}</span>
          </transition>
        </router-link>
      </nav>
      
      <div class="sidebar-footer">
        <div class="user-card" @click="showUserMenu = !showUserMenu">
          <el-avatar :size="36" class="user-avatar">
            {{ authStore.user?.username?.charAt(0)?.toUpperCase() }}
          </el-avatar>
          <transition name="fade">
            <div v-if="!isCollapse" class="user-info">
              <span class="user-name">{{ authStore.user?.username }}</span>
              <span class="user-role">{{ getRoleText(authStore.user?.role) }}</span>
            </div>
          </transition>
        </div>
        
        <!-- 用户菜单 -->
        <transition name="slide-up">
          <div v-if="showUserMenu" class="user-menu">
            <a class="menu-item" @click="handleCommand('profile')">
              <el-icon><User /></el-icon>
              <span>个人中心</span>
            </a>
            <a class="menu-item" @click="handleCommand('settings')">
              <el-icon><Setting /></el-icon>
              <span>设置</span>
            </a>
            <div class="menu-divider"></div>
            <a class="menu-item danger" @click="handleCommand('logout')">
              <el-icon><SwitchButton /></el-icon>
              <span>退出登录</span>
            </a>
          </div>
        </transition>
      </div>
    </aside>
    
    <!-- 主内容区 -->
    <div class="main-container">
      <!-- 顶部导航 -->
      <header class="header">
        <div class="header-left">
          <button class="collapse-btn" @click="isCollapse = !isCollapse">
            <el-icon :size="20">
              <Fold v-if="!isCollapse" />
              <Expand v-else />
            </el-icon>
          </button>
          
          <div class="breadcrumb-wrapper">
            <el-breadcrumb separator="/">
              <el-breadcrumb-item :to="{ path: '/' }">
                <el-icon><HomeFilled /></el-icon>
              </el-breadcrumb-item>
              <el-breadcrumb-item v-if="currentTitle">
                {{ currentTitle }}
              </el-breadcrumb-item>
            </el-breadcrumb>
          </div>
        </div>
        
        <div class="header-right">
          <div class="search-wrapper" :class="{ focused: searchFocused }">
            <el-icon class="search-icon"><Search /></el-icon>
            <input 
              v-model="searchKeyword"
              type="text"
              placeholder="搜索文档..."
              @focus="searchFocused = true"
              @blur="searchFocused = false"
              @keyup.enter="handleSearch"
            />
            <kbd class="search-shortcut">⌘K</kbd>
          </div>
          
          <button class="header-action" title="通知">
            <el-icon :size="20"><Bell /></el-icon>
            <span class="notification-dot"></span>
          </button>
          
          <button class="header-action" title="帮助">
            <el-icon :size="20"><QuestionFilled /></el-icon>
          </button>
        </div>
      </header>
      
      <!-- 页面内容 -->
      <main class="main-content">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
    
    <!-- 点击外部关闭用户菜单 -->
    <div v-if="showUserMenu" class="overlay" @click="showUserMenu = false"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { HomeFilled, Document, ChatDotRound, Setting, Fold, Expand, Search, User, SwitchButton, Bell, QuestionFilled } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const isCollapse = ref(false)
const searchKeyword = ref('')
const searchFocused = ref(false)
const showUserMenu = ref(false)

const menuItems = [
  { path: '/', label: '首页', icon: 'HomeFilled' },
  { path: '/documents', label: '文档管理', icon: 'Document' },
  { path: '/qa', label: '智能问答', icon: 'ChatDotRound', badge: 'AI' },
]

const currentTitle = computed(() => {
  return route.meta.title as string || ''
})

const isActive = (path: string) => {
  if (path === '/') {
    return route.path === '/'
  }
  return route.path.startsWith(path)
}

const getRoleText = (role?: string) => {
  const roles: Record<string, string> = {
    admin: '管理员',
    editor: '编辑者',
    viewer: '查看者'
  }
  return roles[role || ''] || '用户'
}

const handleSearch = () => {
  if (searchKeyword.value.trim()) {
    router.push({
      path: '/documents',
      query: { keyword: searchKeyword.value }
    })
  }
}

const handleCommand = (command: string) => {
  showUserMenu.value = false
  switch (command) {
    case 'profile':
      router.push('/profile')
      break
    case 'settings':
      router.push('/settings')
      break
    case 'logout':
      authStore.logout()
      router.push('/login')
      break
  }
}

// 点击外部关闭菜单
const handleClickOutside = (e: MouseEvent) => {
  const target = e.target as HTMLElement
  if (!target.closest('.user-card') && !target.closest('.user-menu')) {
    showUserMenu.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.main-layout {
  display: flex;
  height: 100vh;
  background: $bg-primary;
}

// Sidebar
.sidebar {
  width: 260px;
  height: 100vh;
  background: $dark-800;
  border-right: 1px solid $border-color;
  display: flex;
  flex-direction: column;
  transition: width $transition-base;
  position: relative;
  z-index: 100;

  &.collapsed {
    width: 72px;
  }
}

.sidebar-header {
  padding: $space-5 $space-5;
  border-bottom: 1px solid $border-color;
}

.logo-wrapper {
  display: flex;
  align-items: center;
  gap: $space-3;
}

.logo-icon {
  width: 36px;
  height: 36px;
  flex-shrink: 0;

  svg {
    width: 100%;
    height: 100%;
  }
}

.logo-text {
  font-family: $font-display;
  font-size: $font-size-lg;
  font-weight: 700;
  color: $text-primary;
  white-space: nowrap;
  letter-spacing: -0.03em;
}

// Nav
.sidebar-nav {
  flex: 1;
  padding: $space-4 $space-3;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: $space-3;
  padding: $space-3 $space-4;
  border-radius: $radius-md;
  color: $text-secondary;
  text-decoration: none;
  transition: all $transition-fast;
  position: relative;

  &:hover {
    background: rgba(245, 158, 11, 0.06);
    color: $text-primary;
  }

  &.active {
    background: rgba(245, 158, 11, 0.1);
    color: $primary-light;

    .nav-icon {
      color: $primary-light;
    }

    &::before {
      content: '';
      position: absolute;
      left: 0;
      top: 50%;
      transform: translateY(-50%);
      width: 3px;
      height: 20px;
      background: $gradient-primary;
      border-radius: 0 3px 3px 0;
    }
  }
}

.nav-icon {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;

  .el-icon {
    font-size: 18px;
  }
}

.nav-text {
  flex: 1;
  font-family: $font-body;
  font-size: $font-size-sm;
  font-weight: 500;
  white-space: nowrap;
}

.nav-badge {
  padding: 2px 8px;
  background: $gradient-primary;
  border-radius: $radius-full;
  font-size: $font-size-xs;
  font-weight: 600;
  color: $dark-900;
}

// Sidebar footer
.sidebar-footer {
  padding: $space-4;
  border-top: 1px solid $border-color;
  position: relative;
}

.user-card {
  display: flex;
  align-items: center;
  gap: $space-3;
  padding: $space-3;
  border-radius: $radius-md;
  cursor: pointer;
  transition: background $transition-fast;

  &:hover {
    background: rgba(245, 158, 11, 0.06);
  }
}

.user-avatar {
  background: $gradient-primary !important;
  font-family: $font-display !important;
  font-weight: 600;
  flex-shrink: 0;
}

.user-info {
  flex: 1;
  min-width: 0;
}

.user-name {
  display: block;
  font-family: $font-body;
  font-size: $font-size-sm;
  font-weight: 600;
  color: $text-primary;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  display: block;
  font-size: $font-size-xs;
  color: $text-muted;
}

// User menu
.user-menu {
  position: absolute;
  bottom: 100%;
  left: $space-3;
  right: $space-3;
  margin-bottom: $space-2;
  background: $dark-700;
  border: 1px solid $border-color;
  border-radius: $radius-lg;
  box-shadow: $shadow-xl;
  overflow: hidden;
  z-index: 1000;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: $space-3;
  padding: $space-3 $space-4;
  color: $text-primary;
  font-family: $font-body;
  text-decoration: none;
  transition: background $transition-fast;
  cursor: pointer;

  &:hover {
    background: rgba(245, 158, 11, 0.06);
  }

  &.danger {
    color: $danger-light;

    &:hover {
      background: rgba(239, 68, 68, 0.1);
    }
  }
}

.menu-divider {
  height: 1px;
  background: $border-color;
  margin: $space-1 0;
}

// Main container
.main-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

// Header
.header {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 $space-6;
  background: $dark-800;
  border-bottom: 1px solid $border-color;
}

.header-left {
  display: flex;
  align-items: center;
  gap: $space-4;
}

.collapse-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid $border-color;
  border-radius: $radius-md;
  color: $text-secondary;
  cursor: pointer;
  transition: all $transition-fast;

  &:hover {
    background: rgba(245, 158, 11, 0.06);
    border-color: $border-color-hover;
    color: $primary-light;
  }
}

.breadcrumb-wrapper {
  :deep(.el-breadcrumb) {
    .el-breadcrumb__inner {
      color: $text-secondary !important;
      font-family: $font-body !important;

      &.is-link:hover {
        color: $primary-light !important;
      }

      &.el-icon {
        font-size: 16px;
      }
    }

    .el-breadcrumb__separator {
      color: $text-muted !important;
    }
  }
}

.header-right {
  display: flex;
  align-items: center;
  gap: $space-3;
}

// Search
.search-wrapper {
  display: flex;
  align-items: center;
  gap: $space-2;
  padding: $space-2 $space-3;
  background: $dark-700;
  border: 1px solid $border-color;
  border-radius: $radius-md;
  transition: all $transition-fast;

  &.focused {
    border-color: $primary-color;
    box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.08);
  }

  .search-icon {
    color: $text-muted;
    font-size: 16px;
  }

  input {
    width: 200px;
    background: transparent;
    border: none;
    outline: none;
    color: $text-primary;
    font-family: $font-body;
    font-size: $font-size-sm;

    &::placeholder {
      color: $text-muted;
    }
  }

  .search-shortcut {
    padding: 2px 6px;
    background: $dark-600;
    border-radius: $radius-sm;
    font-size: $font-size-xs;
    color: $text-muted;
    font-family: $font-mono;
  }
}

.header-action {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid $border-color;
  border-radius: $radius-md;
  color: $text-secondary;
  cursor: pointer;
  transition: all $transition-fast;
  position: relative;

  &:hover {
    background: rgba(245, 158, 11, 0.06);
    border-color: $border-color-hover;
    color: $primary-light;
  }

  .notification-dot {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 8px;
    height: 8px;
    background: $danger-color;
    border-radius: 50%;
    border: 2px solid $dark-800;
  }
}

// Main content
.main-content {
  flex: 1;
  overflow-y: auto;
  background: $bg-primary;
}

// Overlay
.overlay {
  position: fixed;
  inset: 0;
  background: transparent;
  z-index: 99;
}

// Transitions
.fade-enter-active,
.fade-leave-active {
  transition: opacity $transition-fast;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all $transition-base;
}

.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity $transition-base;
}

.page-fade-enter-from,
.page-fade-leave-to {
  opacity: 0;
}

// Responsive
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    z-index: 1000;
    transform: translateX(-100%);

    &:not(.collapsed) {
      transform: translateX(0);
    }
  }

  .search-wrapper {
    display: none;
  }
}
</style>