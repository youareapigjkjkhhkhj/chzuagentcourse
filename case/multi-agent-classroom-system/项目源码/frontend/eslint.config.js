import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'

/**
 * P0-E1：前端 eslint 零错误。规则按「能挡住真问题」来挑，
 * 不做风格警察 —— 风格交给 prettier（本项目暂未接入）。
 */
export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', 'src/components.d.ts'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'] },
    },
  },
  {
    languageOptions: {
      globals: {
        window: 'readonly',
        document: 'readonly',
        crypto: 'readonly',
        // AudioWorklet 那条线程自带的全局量（src/composables/pcm-worklet.js）：
        // 那里没有 window，采样率也不是我们能传进去的参数
        sampleRate: 'readonly',
        currentTime: 'readonly',
        AudioWorkletProcessor: 'readonly',
        registerProcessor: 'readonly',
      },
    },
    rules: {
      // 显式 any 是坏味道，但 TDesign 的部分回调签名只有 any，允许带注释的例外
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      // 单文件组件必须多词命名，否则和 HTML 标签撞名
      'vue/multi-word-component-names': ['error', { ignores: ['App'] }],
      'vue/attribute-hyphenation': 'off',
      'vue/v-on-event-hyphenation': 'off',
      // 排版类规则一律关掉：它们和 prettier 抢活干，而且会把
      // 「一行能写下的按钮」拆成六行。留下的是真会出错的规则
      //（no-mutating-props / require-v-for-key / no-unused-vars …）。
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/multiline-html-element-content-newline': 'off',
      'vue/html-indent': 'off',
      'vue/html-closing-bracket-newline': 'off',
      'vue/html-self-closing': 'off',
      'vue/attributes-order': 'off',
      'vue/first-attribute-linebreak': 'off',
    },
  },
)
