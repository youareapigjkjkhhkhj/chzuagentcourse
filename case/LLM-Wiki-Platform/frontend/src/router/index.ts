import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/auth/LoginView.vue'),
    meta: { requiresAuth: false, title: '登录' }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/auth/RegisterView.vue'),
    meta: { requiresAuth: false, title: '注册' }
  },
  {
    path: '/',
    component: () => import('@/components/layout/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Home',
        component: () => import('@/views/HomeView.vue'),
        meta: { title: '首页' }
      },
      {
        path: 'documents',
        name: 'DocumentList',
        component: () => import('@/views/documents/DocumentListView.vue'),
        meta: { title: '文档列表' }
      },
      {
        path: 'documents/:id',
        name: 'DocumentDetail',
        component: () => import('@/views/documents/DocumentDetailView.vue'),
        meta: { title: '文档详情' }
      },
      {
        path: 'documents/create',
        name: 'DocumentCreate',
        component: () => import('@/views/documents/DocumentEditView.vue'),
        meta: { title: '创建文档', requiresEditor: true }
      },
      {
        path: 'documents/:id/edit',
        name: 'DocumentEdit',
        component: () => import('@/views/documents/DocumentEditView.vue'),
        meta: { title: '编辑文档', requiresEditor: true }
      },
      {
        path: 'qa',
        name: 'QAChat',
        component: () => import('@/views/qa/QAChatView.vue'),
        meta: { title: '智能问答' }
      },
      {
        path: 'qa/history',
        name: 'QAHistory',
        component: () => import('@/views/qa/QAHistoryView.vue'),
        meta: { title: '问答历史' }
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/error/NotFoundView.vue'),
    meta: { title: '404' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  
  // 设置页面标题
  document.title = `${to.meta.title || ''} - LLM Wiki知识管理平台`
  
  // 检查是否需要认证
  if (to.meta.requiresAuth !== false && !authStore.isAuthenticated) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
    return
  }
  
  next()
})

export default router