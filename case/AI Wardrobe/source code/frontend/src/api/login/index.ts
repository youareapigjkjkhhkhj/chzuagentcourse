import request from '@/axios'
import type { AdminLoginResponseType, SmsCodeResponseType, UserLoginType, UserType } from './types'

/**
 * 管理员登录（真实后端接口）
 * 后端：kaleido-auth AdminAuthController /public/admin/login
 * 入参：{ mobile, verifyCode }；出参：{ userId, token, userInfo }
 */
export const loginApi = (data: UserLoginType): Promise<IResponse<AdminLoginResponseType>> => {
  return request.post({ url: '/kaleido-auth/public/admin/login', data })
}

/**
 * 发送短信验证码（真实后端接口）
 * 后端：kaleido-auth SmsController /public/sms/verify-code
 * 注意：同一手机号 60 秒内限流 1 次；当前后端短信发送为空实现，
 * 验证码会直接在响应 data.code 中返回
 */
export const sendSmsCodeApi = (data: SmsCodeType): Promise<IResponse<SmsCodeResponseType>> => {
  return request.post({ url: '/kaleido-auth/public/sms/verify-code', data })
}

export const loginOutApi = (): Promise<IResponse> => {
  return request.get({ url: '/mock/user/loginOut' })
}

export const getUserListApi = ({ params }: AxiosConfig) => {
  return request.get<{
    code: string
    data: {
      list: UserType[]
      total: number
    }
  }>({ url: '/mock/user/list', params })
}

export const getAdminRoleApi = (
  params: RoleParams
): Promise<IResponse<AppCustomRouteRecordRaw[]>> => {
  return request.get({ url: '/mock/role/list', params })
}

export const getTestRoleApi = (params: RoleParams): Promise<IResponse<string[]>> => {
  return request.get({ url: '/mock/role/list2', params })
}

interface RoleParams {
  roleName: string
}
