export interface UserLoginType {
  mobile: string
  verifyCode: string
}

export interface SmsCodeType {
  mobile: string
  targetType: string
}

export interface AdminUserInfoType {
  adminId: string
  realName: string
  mobile: string
  status: string
  lastLoginTime?: string
  roleIds?: string[]
  // 前端展示扩展字段
  username?: string
  roles?: string[]
}

export interface AdminLoginResponseType {
  userId: string
  token: string
  userInfo: AdminUserInfoType
}

export interface SmsCodeResponseType {
  mobile: string
  code: string
  sendTime: string
}

export interface UserType {
  username?: string
  password?: string
  role?: string
  roleId?: string
  [key: string]: any
}
