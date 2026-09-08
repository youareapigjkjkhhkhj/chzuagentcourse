/** esbuild 打包 Main / Preload（CJS 输出，electron 保持 external） */
import { build } from 'esbuild';

const common = {
  bundle: true,
  platform: 'node',
  target: 'node20',
  format: 'cjs',
  external: ['electron'],
  logLevel: 'info',
};

await Promise.all([
  build({
    ...common,
    entryPoints: ['src/main/index.ts'],
    outfile: 'dist/main/index.cjs',
  }),
  build({
    ...common,
    entryPoints: ['src/preload/index.ts'],
    outfile: 'dist/main/preload.cjs',
  }),
]);
