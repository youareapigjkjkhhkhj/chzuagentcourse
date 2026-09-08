// 用户类型定义
export interface User {
  id: number
  username: string
  email: string
  real_name?: string
  department?: string
  position?: string
  phone?: string
  avatar?: string
  role: 'admin' | 'editor' | 'viewer'
  status: 'active' | 'inactive' | 'locked'
  last_login_at?: string
  created_at: string
}