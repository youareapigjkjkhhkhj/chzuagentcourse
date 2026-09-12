/**
 * 路由（P0 §2 F0-4）：顶栏四页。
 *
 * 用懒加载：首页之外的三个页面在 P0 都还只有占位内容，没必要让它们
 * 挤进首屏包（P0-D2 首屏可交互 ≤ 1.5s / P0-D3 gzip ≤ 800KB）。
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'index',
    component: () => import('@/views/IndexView.vue'),
    meta: { title: '首页' },
  },
  {
    path: '/workbench',
    name: 'workbench',
    component: () => import('@/views/WorkbenchView.vue'),
    meta: { title: '工作台' },
  },
  {
    path: '/classroom',
    name: 'classroom',
    component: () => import('@/views/ClassroomView.vue'),
    meta: { title: '课堂演示' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { title: '设置' },
  },
  // 兜底：写错的地址回到首页，而不是留在空白页
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  const title = (to.meta.title as string | undefined) ?? ''
  document.title = title ? `${title} | EduAgentX` : 'EduAgentX · 多智能体互动课堂'
})

export default router
