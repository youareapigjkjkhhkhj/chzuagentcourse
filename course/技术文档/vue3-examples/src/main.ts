import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
// 如果要演示路由，取消下面注释
// import { router } from './router'

const app = createApp(App)

app.use(createPinia())
// 如果要演示路由，取消下面注释
// app.use(router)

app.mount('#app')
