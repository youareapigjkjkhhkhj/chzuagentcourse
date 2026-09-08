/** 与原型 AgentBuddy_原型_v2.1_优化版.html 的 tailwind.config 完全一致 */
module.exports = {
  content: ['./src/renderer/index.html', './src/renderer/src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        // 奶白（Cream）主题：对齐 Claude 桌面端的暖白纸感
        sidebar: '#f1efe9',
        main: '#faf9f6',
        card: '#ffffff',
        cardHover: '#f5f2ec',
        surface: '#f3f1ea',
        border: '#e6e2d9',
        borderLight: '#d5cfc2',
        accent: '#c96f4a',
        accentDim: '#b25a37',
        // 可读性优化：stone 400-700 整体加深一档（小字号辅助文本/图标不再发灰发浅）
        stone: {
          400: '#918a80',
          500: '#67615a',
          600: '#4a4540',
          700: '#3b3733',
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'Consolas', 'monospace'],
        sans: ['"Inter"', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(28,25,20,.05), 0 0 0 1px rgba(28,25,20,.02) inset',
        popover: '0 12px 32px -8px rgba(28,25,20,.16), 0 0 0 1px rgba(28,25,20,.04)',
        glow: '0 0 0 1px rgba(201,111,74,.30), 0 8px 40px -8px rgba(201,111,74,.22)',
      },
    },
  },
  plugins: [],
};
