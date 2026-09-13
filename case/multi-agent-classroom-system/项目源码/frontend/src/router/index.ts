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
    // 课堂记录回看（P3-6）。下课之后自动跳到这里，也可以从记录里点回来。
    // **排在 `/classroom` 之后没有关系**：两条路径的段数不同，先匹配谁都不冲突。
    // `meta.nav` 让顶栏仍然把「课堂演示」点亮 —— 人还在这堂课的上下文里，
    // 这时候四个链接全暗着，看起来像掉出了应用（见 `AppHeader` 的 `activeName`）。
    path: '/classroom/record',
    name: 'classroom-record',
    component: () => import('@/views/ClassroomRecordView.vue'),
    meta: { title: '课堂记录', nav: 'classroom' },
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
