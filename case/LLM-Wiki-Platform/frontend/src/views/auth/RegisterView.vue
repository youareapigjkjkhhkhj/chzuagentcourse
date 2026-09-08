<template>
  <div class="register-page">
    <div class="register-container">
      <div class="register-header">
        <img src="@/assets/logo.svg" alt="Logo" class="logo" />
        <h1>注册账号</h1>
        <p>加入LLM Wiki知识管理平台</p>
      </div>
      
      <el-form ref="formRef" :model="form" :rules="rules" class="register-form">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            prefix-icon="User"
            size="large"
          />
        </el-form-item>
        
        <el-form-item prop="email">
          <el-input
            v-model="form.email"
            placeholder="请输入邮箱"
            prefix-icon="Message"
            size="large"
          />
        </el-form-item>
        
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            prefix-icon="Lock"
            size="large"
            show-password
          />
        </el-form-item>
        
        <el-form-item prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            placeholder="请确认密码"
            prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleRegister"
          />
        </el-form-item>
        
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="register-btn"
            @click="handleRegister"
          >
            注册
          </el-button>
        </el-form-item>
        
        <div class="register-footer">
          <span>已有账号？</span>
          <router-link to="/login">立即登录</router-link>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: ''
})

const validateConfirmPassword = (rule: any, value: string, callback: any) => {
  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度在3到50个字符', trigger: 'blur' }
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, message: '密码长度不能少于8个字符', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' }
  ]
}

const handleRegister = async () => {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true
      try {
        const result = await authStore.register({
          username: form.username,
          email: form.email,
          password: form.password
        })
        if (result.success) {
          ElMessage.success('注册成功')
          router.push('/login')
        } else {
          ElMessage.error(result.error || '注册失败')
        }
      } catch (error) {
        ElMessage.error('注册失败，请稍后重试')
      } finally {
        loading.value = false
      }
    }
  })
}
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.register-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: $bg-primary;
}

.register-container {
  width: 400px;
  padding: $space-10;
  background: $bg-card;
  backdrop-filter: blur(12px);
  border-radius: $radius-xl;
  border: 1px solid $border-color;
  box-shadow: $shadow-xl;
}

.register-header {
  text-align: center;
  margin-bottom: $space-8;

  .logo {
    width: 60px;
    height: 60px;
    margin-bottom: $space-4;
  }

  h1 {
    font-family: $font-display;
    font-size: $font-size-2xl;
    font-weight: 700;
    color: $text-primary;
    margin: 0 0 $space-2 0;
    letter-spacing: -0.03em;
  }

  p {
    margin: 0;
    color: $text-secondary;
    font-size: $font-size-sm;
  }
}

.register-form {
  .register-btn {
    width: 100%;
    font-family: $font-display;
    font-weight: 600;
  }
}

.register-footer {
  text-align: center;
  color: $text-muted;
  font-size: $font-size-sm;

  a {
    color: $primary-light;
    font-weight: 600;
    text-decoration: none;

    &:hover {
      text-decoration: underline;
    }
  }
}
</style>