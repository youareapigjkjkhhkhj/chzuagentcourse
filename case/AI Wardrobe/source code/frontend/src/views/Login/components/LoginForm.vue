<script setup lang="tsx">
import { reactive, ref, watch, onMounted, onUnmounted, unref } from 'vue'
import { Form, FormSchema } from '@/components/Form'
import { useI18n } from '@/hooks/web/useI18n'
import { ElCheckbox } from 'element-plus'
import { ElMessage } from 'element-plus'
import { useForm } from '@/hooks/web/useForm'
import { loginApi, sendSmsCodeApi } from '@/api/login'
import { useAppStore } from '@/store/modules/app'
import { usePermissionStore } from '@/store/modules/permission'
import { useRouter } from 'vue-router'
import type { RouteLocationNormalizedLoaded, RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/store/modules/user'
import { BaseButton } from '@/components/Button'
import { useValidator } from '@/hooks/web/useValidator'

const { required, phone } = useValidator()

const appStore = useAppStore()

const userStore = useUserStore()

const permissionStore = usePermissionStore()

const { currentRoute, addRoute, push } = useRouter()

const { t } = useI18n()

const rules = {
  mobile: [required('手机号不能为空'), phone()],
  verifyCode: [required('验证码不能为空')]
}

const schema = reactive<FormSchema[]>([
  {
    field: 'title',
    colProps: {
      span: 24
    },
    formItemProps: {
      slots: {
        default: () => {
          return <h2 class="text-2xl font-bold text-center w-[100%]">{t('login.login')}</h2>
        }
      }
    }
  },
  {
    field: 'mobile',
    label: '手机号',
    component: 'Input',
    colProps: {
      span: 24
    },
    componentProps: {
      placeholder: '请输入手机号',
      maxlength: 11,
      // 按下enter键触发登录
      onKeydown: (_e: any) => {
        if (_e.key === 'Enter') {
          _e.stopPropagation() // 阻止事件冒泡
          signIn()
        }
      }
    }
  },
  {
    field: 'verifyCode',
    label: '短信验证码',
    component: 'Input',
    colProps: {
      span: 24
    },
    componentProps: {
      placeholder: '请输入短信验证码',
      maxlength: 8,
      // 按下enter键触发登录
      onKeydown: (_e: any) => {
        if (_e.key === 'Enter') {
          _e.stopPropagation() // 阻止事件冒泡
          signIn()
        }
      }
    }
  },
  {
    field: 'sendCode',
    colProps: {
      span: 24
    },
    formItemProps: {
      slots: {
        default: () => {
          return (
            <div class="w-[100%]">
              <BaseButton
                type="default"
                class="w-[100%]"
                loading={sendLoading.value}
                disabled={countdown.value > 0}
                onClick={sendCode}
              >
                {countdown.value > 0 ? `${countdown.value}s 后可重新发送` : '发送验证码'}
              </BaseButton>
              <div
                class="text-xs text-center w-[100%] mt-5px"
                style="color: var(--el-text-color-secondary)"
              >
                {countdownTip.value}
              </div>
            </div>
          )
        }
      }
    }
  },
  {
    field: 'tool',
    colProps: {
      span: 24
    },
    formItemProps: {
      slots: {
        default: () => {
          return (
            <>
              <div class="flex justify-between items-center w-[100%]">
                <ElCheckbox v-model={remember.value} label={t('login.remember')} size="small" />
              </div>
            </>
          )
        }
      }
    }
  },
  {
    field: 'login',
    colProps: {
      span: 24
    },
    formItemProps: {
      slots: {
        default: () => {
          return (
            <>
              <div class="w-[100%]">
                <BaseButton
                  loading={loading.value}
                  type="primary"
                  class="w-[100%]"
                  onClick={signIn}
                >
                  {t('login.login')}
                </BaseButton>
              </div>
            </>
          )
        }
      }
    }
  }
])

const remember = ref(userStore.getRememberMe)

const initLoginInfo = () => {
  const loginInfo = userStore.getLoginInfo
  if (loginInfo) {
    const { username } = loginInfo
    if (username) {
      setValues({ mobile: username })
    }
  }
}
onMounted(() => {
  initLoginInfo()
})

const { formRegister, formMethods } = useForm()
const { getFormData, getElFormExpose, setValues } = formMethods

const loading = ref(false)

// 发送验证码相关状态
const sendLoading = ref(false)
const countdown = ref(0)
const countdownTip = ref('')
let timer: ReturnType<typeof setInterval> | undefined

const stopCountdown = () => {
  if (timer) {
    clearInterval(timer)
    timer = undefined
  }
}

onUnmounted(() => {
  stopCountdown()
})

// 发送短信验证码（后端限流：60 秒 1 次）
const sendCode = async () => {
  if (countdown.value > 0) return
  const formRef = await getElFormExpose()
  if (!formRef) return
  const valid = await formRef.validateField(['mobile']).catch(() => false)
  if (!valid) return
  const formData = await getFormData<{ mobile: string }>()
  sendLoading.value = true
  try {
    const res = await sendSmsCodeApi({ mobile: formData.mobile, targetType: 'ADMIN' })
    if (res) {
      // 当前后端短信发送为空实现，验证码直接在响应 data.code 中返回
      if (res?.data?.code) {
        countdownTip.value = `（演示模式：验证码 ${res.data.code}，有效期 5 分钟）`
        ElMessage.success(`验证码已发送：${res.data.code}`)
      } else {
        countdownTip.value = '验证码已发送，请注意查收短信'
        ElMessage.success('验证码已发送')
      }
      countdown.value = 60
      timer = setInterval(() => {
        countdown.value -= 1
        if (countdown.value <= 0) {
          stopCountdown()
          countdownTip.value = ''
        }
      }, 1000)
    }
  } finally {
    sendLoading.value = false
  }
}

const redirect = ref<string>('')

watch(
  () => currentRoute.value,
  (route: RouteLocationNormalizedLoaded) => {
    redirect.value = route?.query?.redirect as string
  },
  {
    immediate: true
  }
)

// 登录
const signIn = async () => {
  const formRef = await getElFormExpose()
  await formRef?.validate(async (isValid) => {
    if (isValid) {
      loading.value = true
      const formData = await getFormData<{ mobile: string; verifyCode: string }>()

      try {
        const res = await loginApi({
          mobile: formData.mobile,
          verifyCode: formData.verifyCode
        })

        if (res) {
          // 是否记住我（记住手机号）
          if (unref(remember)) {
            userStore.setLoginInfo({
              username: formData.mobile,
              password: ''
            })
          } else {
            userStore.setLoginInfo(undefined)
          }
          userStore.setRememberMe(unref(remember))
          // sa-token 管理端 token 请求头名称为 kaleido-admin-token
          userStore.setTokenKey('kaleido-admin-token')
          userStore.setToken(res?.data?.token ?? '')
          const userInfo = {
            ...(res?.data?.userInfo ?? {}),
            username: res?.data?.userInfo?.realName || formData.mobile,
            roles: ['admin']
          }
          userStore.setUserInfo(userInfo as any)
          // 是否使用动态路由
          if (appStore.getDynamicRouter) {
            getRole()
          } else {
            await permissionStore.generateRoutes('static').catch(() => {})
            permissionStore.getAddRouters.forEach((route) => {
              addRoute(route as RouteRecordRaw) // 动态添加可访问路由表
            })
            permissionStore.setIsAddRouters(true)
            push({ path: redirect.value || permissionStore.addRouters[0].path })
          }
        }
      } finally {
        loading.value = false
      }
    }
  })
}

// 获取角色信息（服务端动态路由，当前未启用）
const getRole = async () => {
  await permissionStore.generateRoutes('static').catch(() => {})
  permissionStore.getAddRouters.forEach((route) => {
    addRoute(route as RouteRecordRaw)
  })
  permissionStore.setIsAddRouters(true)
  push({ path: redirect.value || permissionStore.addRouters[0].path })
}
</script>

<template>
  <Form
    :schema="schema"
    :rules="rules"
    label-position="top"
    hide-required-asterisk
    size="large"
    class="dark:(border-1 border-[var(--el-border-color)] border-solid)"
    @register="formRegister"
  />
</template>
