import vue from '@vitejs/plugin-vue';
import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  root: 'src/renderer',
  // img src 保持原样（指向 public/ 下的静态素材），不做模块解析
  plugins: [vue({ template: { transformAssetUrls: { img: [] } } })],
  resolve: {
    alias: {
      '@agentbuddy/shared': fileURLToPath(new URL('../../packages/shared/src/index.ts', import.meta.url)),
    },
  },
  build: {
    outDir: '../../dist/renderer',
    emptyOutDir: true,
  },
});
