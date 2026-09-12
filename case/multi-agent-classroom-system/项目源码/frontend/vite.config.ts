import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { TDesignResolver } from 'unplugin-vue-components/resolvers'
// 从 vitest/config 取 defineConfig：它比 vite 的多认识一个 `test` 字段
import { defineConfig } from 'vitest/config'

/**
 * 后端端口。开发态前端只跟自己的 Flask 说话，绝不直连任何厂商
 * （AGENTS.md §4.1：浏览器侧不得出现任何厂商凭据 —— 凭据全在服务端）。
 */
const BACKEND = process.env.BACKEND_ORIGIN || 'http://127.0.0.1:5000'

export default defineConfig({
  plugins: [
    vue(),
    // TDesign 按需引入：引一个组件才会进包，否则 P0-D3 的
    // 「gzip 后 JS ≤ 800KB」一上来就超（整包 TDesign 约 1.2MB gzip）
    Components({
      resolvers: [TDesignResolver({ library: 'vue-next' })],
      dts: 'src/components.d.ts',
    }),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
  // vitest 与 dev server 默认共用 node_modules/.vite 依赖缓存：dev server
  // 冷启动时正在写这份缓存，此时并行跑的 vitest 会读到半成品而失败
  //（验收脚本里就是这么挂的：A1 刚拉起 dev server，A2 紧接着跑测试）。
  // 给测试单开一个缓存目录，两边互不干扰。
  cacheDir: process.env.VITEST ? 'node_modules/.vite-test' : 'node_modules/.vite',
  build: {
    outDir: 'dist',
    // 关掉 sourcemap：产物体积要进验收，map 会把 dist 撑大一倍多
    sourcemap: false,
    chunkSizeWarningLimit: 1024,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.spec.ts'],
    // 前端测试也不联网（AGENTS.md §23）：所有请求都打桩
    setupFiles: ['src/__tests__/setup.ts'],
    // 默认 5s 对 jsdom 太紧：某个用例第一次挂载 TDesign 的重组件
    //（设置页的 Drawer/Slider/Radio…）时，转换成本全落在它头上，
    // 之后同样的挂载只要几十毫秒。放宽到 15s 是为了不把
    //「机器在编译」误判成「代码挂了」—— 真卡死的用例照样会超时。
    testTimeout: 15000,
  },
})
