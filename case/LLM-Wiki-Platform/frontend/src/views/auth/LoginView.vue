<template>
  <div class="login-page">
    <!-- 左侧品牌区域 -->
    <div class="brand-section">
      <div class="brand-content">
        <div class="brand-header fade-in-up">
          <div class="logo-wrapper">
            <div class="logo-icon">
              <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="40" height="40" rx="10" fill="url(#logo-gradient)"/>
                <path d="M12 14h16v2H12v-2zm0 4h16v2H12v-2zm0 4h10v2H12v-2z" fill="white"/>
                <defs>
                  <linearGradient id="logo-gradient" x1="0" y1="0" x2="40" y2="40">
                    <stop stop-color="#0ea5e9"/>
                    <stop offset="1" stop-color="#6366f1"/>
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <span class="logo-text">LLM Wiki</span>
          </div>
          
          <h1 class="brand-title">
            智能知识管理
            <span class="gradient-text">新一代</span>
            企业运维平台
          </h1>
          
          <p class="brand-description">
            基于大语言模型的企业级知识管理系统，让运维知识触手可及
          </p>
        </div>
        
        <div class="features-list fade-in-up delay-2">
          <div class="feature-item">
            <div class="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
              </svg>
            </div>
            <div class="feature-text">
              <h3>AI 驱动问答</h3>
              <p>自然语言理解，精准答案生成</p>
            </div>
          </div>
          
          <div class="feature-item">
            <div class="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
              </svg>
            </div>
            <div class="feature-text">
              <h3>知识库管理</h3>
              <p>结构化存储，快速检索</p>
            </div>
          </div>
          
          <div class="feature-item">
            <div class="feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
              </svg>
            </div>
            <div class="feature-text">
              <h3>企业级安全</h3>
              <p>权限控制，数据加密</p>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 装饰性背景 -->
      <div class="brand-decoration">
        <div class="grid-pattern"></div>
        <div class="glow-circle glow-circle-1"></div>
        <div class="glow-circle glow-circle-2"></div>
        <div class="floating-elements">
          <div class="float-element float-element-1"></div>
          <div class="float-element float-element-2"></div>
          <div class="float-element float-element-3"></div>
        </div>
      </div>
    </div>
    
    <!-- 右侧登录表单 -->
    <div class="form-section">
      <div class="form-wrapper fade-in-up delay-1">
        <div class="form-header">
          <h2>欢迎回来</h2>
          <p>登录您的账户以继续</p>
        </div>
        
        <el-form ref="formRef" :model="form" :rules="rules" class="login-form" @submit.prevent>
          <el-form-item prop="username">
            <div class="input-group">
              <label>用户名</label>
              <el-input
                v-model="form.username"
                placeholder="请输入用户名"
                size="large"
                :prefix-icon="User"
              />
            </div>
          </el-form-item>
          
          <el-form-item prop="password">
            <div class="input-group">
              <label>密码</label>
              <el-input
                v-model="form.password"
                type="password"
                placeholder="请输入密码"
                size="large"
                show-password
                :prefix-icon="Lock"
                @keyup.enter="handleLogin"
              />
            </div>
          </el-form-item>
          
          <div class="form-options">
            <el-checkbox v-model="rememberMe">记住我</el-checkbox>
            <a href="#" class="forgot-link">忘记密码？</a>
          </div>
          
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="login-btn"
            @click="handleLogin"
          >
            <span v-if="!loading">登录</span>
            <span v-else>登录中...</span>
          </el-button>
        </el-form>
        
        <div class="form-footer">
          <p>还没有账号？ <router-link to="/register">立即注册</router-link></p>
        </div>
        
        <div class="divider">
          <span>或</span>
        </div>
        
        <div class="demo-hint">
          <p>演示账户: <code>admin</code> / <code>admin123456</code></p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const rememberMe = ref(false)

const form = reactive({
  username: '',
  password: ''
})

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' }
  ]
}

const handleLogin = async () => {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true
      try {
        const result = await authStore.login(form.username, form.password)
        if (result.success) {
          ElMessage.success('登录成功')
          const redirect = route.query.redirect as string || '/'
          router.push(redirect)
        } else {
          ElMessage.error(result.error || '登录失败')
        }
      } catch (error) {
        ElMessage.error('登录失败，请稍后重试')
      } finally {
        loading.value = false
      }
    }
  })
}
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.login-page {
  display: flex;
  min-height: 100vh;
  background: $bg-primary;
}

// Left brand section
.brand-section {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: $space-10;
  overflow: hidden;
  background: $gradient-dark;
}

.brand-content {
  position: relative;
  z-index: 10;
  max-width: 500px;
}

.brand-header {
  margin-bottom: $space-10;
}

.logo-wrapper {
  display: flex;
  align-items: center;
  gap: $space-3;
  margin-bottom: $space-8;
}

.logo-icon {
  width: 48px;
  height: 48px;

  svg {
    width: 100%;
    height: 100%;
  }
}

.logo-text {
  font-family: $font-display;
  font-size: $font-size-2xl;
  font-weight: 700;
  color: $text-primary;
  letter-spacing: -0.04em;
}

.brand-title {
  font-family: $font-display;
  font-size: $font-size-4xl;
  font-weight: 800;
  color: $text-primary;
  line-height: 1.15;
  margin-bottom: $space-4;
  letter-spacing: -0.04em;
}

.gradient-text {
  background: $gradient-primary;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.brand-description {
  font-size: $font-size-lg;
  color: $text-secondary;
  line-height: 1.6;
}

.features-list {
  display: flex;
  flex-direction: column;
  gap: $space-5;
}

.feature-item {
  display: flex;
  align-items: flex-start;
  gap: $space-4;
  padding: $space-4 $space-5;
  border-radius: $radius-lg;
  background: rgba(245, 158, 11, 0.03);
  border: 1px solid $border-color;
  transition: all $transition-base;

  &:hover {
    background: rgba(245, 158, 11, 0.06);
    border-color: $border-color-hover;
    transform: translateX(8px);
  }
}

.feature-icon {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: $gradient-primary;
  border-radius: $radius-md;
  color: $dark-900;

  svg {
    width: 24px;
    height: 24px;
  }
}

.feature-text {
  h3 {
    font-family: $font-display;
    font-size: $font-size-base;
    font-weight: 600;
    color: $text-primary;
    margin-bottom: $space-1;
  }

  p {
    font-size: $font-size-sm;
    color: $text-secondary;
    margin: 0;
  }
}

// Decorative background
.brand-decoration {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

.grid-pattern {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(245, 158, 11, 0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(245, 158, 11, 0.025) 1px, transparent 1px);
  background-size: 50px 50px;
}

.glow-circle {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);

  &-1 {
    width: 400px;
    height: 400px;
    background: rgba(245, 158, 11, 0.12);
    top: -100px;
    right: -100px;
    animation: float 6s ease-in-out infinite;
  }

  &-2 {
    width: 300px;
    height: 300px;
    background: rgba(239, 68, 68, 0.08);
    bottom: -50px;
    left: -50px;
    animation: float 8s ease-in-out infinite reverse;
  }
}

.floating-elements {
  position: absolute;
  inset: 0;
}

.float-element {
  position: absolute;
  border-radius: $radius-lg;
  background: $gradient-primary;
  opacity: 0.08;

  &-1 {
    width: 60px;
    height: 60px;
    top: 20%;
    left: 10%;
    animation: float 5s ease-in-out infinite;
  }

  &-2 {
    width: 40px;
    height: 40px;
    top: 60%;
    right: 15%;
    animation: float 7s ease-in-out infinite reverse;
    transform: rotate(45deg);
  }

  &-3 {
    width: 80px;
    height: 80px;
    bottom: 20%;
    left: 20%;
    animation: float 6s ease-in-out infinite;
    border-radius: 50%;
  }
}

// Right form section
.form-section {
  width: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: $space-10;
  background: $dark-800;
  border-left: 1px solid $border-color;
}

.form-wrapper {
  width: 100%;
  max-width: 360px;
}

.form-header {
  margin-bottom: $space-8;

  h2 {
    font-family: $font-display;
    font-size: $font-size-2xl;
    font-weight: 700;
    color: $text-primary;
    margin: 0 0 $space-2 0;
    letter-spacing: -0.03em;
  }

  p {
    font-size: $font-size-base;
    color: $text-secondary;
    margin: 0;
  }
}

.login-form {
  :deep(.el-form-item) {
    margin-bottom: $space-5;
  }
}

.input-group {
  width: 100%;

  label {
    display: block;
    font-family: $font-body;
    font-size: $font-size-sm;
    font-weight: 500;
    color: $text-secondary;
    margin-bottom: $space-2;
  }

  :deep(.el-input) {
    width: 100%;

    .el-input__wrapper {
      background: $dark-700 !important;
      border: 1px solid $border-color !important;
      box-shadow: none !important;

      &:hover {
        border-color: $border-color-hover !important;
      }

      &.is-focus {
        border-color: $primary-color !important;
        box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.08) !important;
      }
    }

    .el-input__prefix {
      color: $text-muted;
    }
  }
}

.form-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $space-6;

  :deep(.el-checkbox) {
    .el-checkbox__label {
      color: $text-secondary;
      font-family: $font-body;
      font-size: $font-size-sm;
    }

    .el-checkbox__inner {
      background: $dark-700;
      border-color: $border-color;
    }

    .el-checkbox__input.is-checked {
      .el-checkbox__inner {
        background: $primary-color;
        border-color: $primary-color;
      }
    }
  }
}

.forgot-link {
  font-size: $font-size-sm;
  color: $primary-light;
  text-decoration: none;

  &:hover {
    text-decoration: underline;
  }
}

.login-btn {
  width: 100%;
  height: 48px;
  font-family: $font-display;
  font-size: $font-size-base;
  font-weight: 600;
  border-radius: $radius-md;
  background: $gradient-primary !important;
  border: none !important;
  transition: all $transition-base !important;

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 0 36px rgba(245, 158, 11, 0.35);
  }

  &:active {
    transform: translateY(0);
  }
}

.form-footer {
  text-align: center;
  margin-top: $space-6;

  p {
    font-size: $font-size-sm;
    color: $text-secondary;
    margin: 0;
  }

  a {
    color: $primary-light;
    font-weight: 600;
    text-decoration: none;

    &:hover {
      text-decoration: underline;
    }
  }
}

.divider {
  display: flex;
  align-items: center;
  margin: $space-6 0;

  &::before,
  &::after {
    content: '';
    flex: 1;
    height: 1px;
    background: $border-color;
  }

  span {
    padding: 0 $space-4;
    font-size: $font-size-sm;
    color: $text-muted;
  }
}

.demo-hint {
  text-align: center;
  padding: $space-4;
  background: rgba(245, 158, 11, 0.06);
  border-radius: $radius-md;
  border: 1px solid rgba(245, 158, 11, 0.12);

  p {
    font-size: $font-size-sm;
    color: $text-secondary;
    margin: 0;
  }

  code {
    font-family: $font-mono;
    background: $dark-700;
    padding: 2px 7px;
    border-radius: $radius-sm;
    color: $primary-light;
    font-size: $font-size-xs;
  }
}

// Responsive
@media (max-width: 1024px) {
  .brand-section {
    display: none;
  }

  .form-section {
    width: 100%;
    border-left: none;
  }
}

.delay-1 { animation-delay: 0.1s; }
.delay-2 { animation-delay: 0.2s; }
.delay-3 { animation-delay: 0.3s; }
.delay-4 { animation-delay: 0.4s; }
</style>