import api from './index'
import type { User } from '@/types/user'

export const authApi = {
  // 登录
  async login(username: string, password: string): Promise<{ user: User; access_token: string; refresh_token: string }> {
    return api.post('/auth/login', { username, password })
  },

  // 注册
  async register(data: { username: string; email: string; password: string }): Promise<{ user: User }> {
    return api.post('/auth/register', data)
  },

  // 获取当前用户
  async getMe(): Promise<{ user: User }> {
    return api.get('/auth/me')
  },

  // 刷新令牌
  async refreshToken(): Promise<{ access_token: string }> {
    return api.post('/auth/refresh')
  }
}