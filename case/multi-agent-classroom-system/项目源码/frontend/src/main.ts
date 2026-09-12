import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from '@/App.vue'
import router from '@/router'

// 顺序要紧：TDesign 的基础令牌表必须先落地，我们自己的 tokens.css 才能覆盖它。
// 按需引入（unplugin-vue-components）只会带进「用到的组件」的样式，
// 这份基础表不会被自动带进来 —— 少了它，组件里的 var(--td-comp-size-m)、
// var(--td-font-body-medium) 全是未定义变量，按钮高度、字号、圆角会集体失效。
import 'tdesign-vue-next/es/style/index.css'
import '@/styles/tokens.css'

createApp(App).use(createPinia()).use(router).mount('#app')
