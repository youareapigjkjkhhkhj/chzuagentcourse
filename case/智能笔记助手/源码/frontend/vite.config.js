import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发态：将 /api 反向代理到 Flask 后端（端口 5000）
// 生产态：build 产物 dist/ 可由 Flask 同源托管，无需代理
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500
  }
})
