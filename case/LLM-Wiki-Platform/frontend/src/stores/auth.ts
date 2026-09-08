import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { User } from '@/types/user'
import { authApi } from '@/api/auth'
import { setToken, getToken, removeToken, setUser, getUser, removeUser } from '@/utils/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(getUser())
  const token = ref<string | null>(getToken())
  const loading = ref(false)

  // 计算属性
  const isAuthenticated = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isEditor = computed(() => ['admin', 'editor'].includes(user.value?.role || ''))

  // 登录
  async function login(username: string, password: string) {
    loading.value = true
    try {
      const response = await authApi.login(username, password)
      user.value = response.user
      token.value = response.access_token
      setToken(response.access_token)
      setUser(response.user)
      return { success: true }
    } catch (error: any) {
      return { success: false, error: error.message }
    } finally {
      loading.value = false
    }
  }

  // 注册
  async function register(data: { username: string; email: string; password: string }) {
    loading.value = true
    try {
      const response = await authApi.register(data)
      user.value = response.user
      setUser(response.user)
      return { success: true }
    } catch (error: any) {
      return { success: false, error: error.message }
    } finally {
      loading.value = false
    }
  }

  // 获取当前用户信息
  async function fetchCurrentUser() {
    if (!token.value) return
    
    loading.value = true
    try {
      const response = await authApi.getMe()
      user.value = response.user
      setUser(response.user)
    } catch (error) {
      // Token无效，清除状态
      logout()
    } finally {
      loading.value = false
    }
  }

  // 登出
  function logout() {
    user.value = null
    token.value = null
    removeToken()
    removeUser()
  }

  return {
    user,
    token,
    loading,
    isAuthenticated,
    isAdmin,
    isEditor,
    login,
    register,
    fetchCurrentUser,
    logout
  }
})