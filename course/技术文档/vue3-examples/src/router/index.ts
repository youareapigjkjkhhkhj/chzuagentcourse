import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'

const routes = [
  { path: '/', component: Home },
  { path: '/about', component: () => import('../views/About.vue') },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
