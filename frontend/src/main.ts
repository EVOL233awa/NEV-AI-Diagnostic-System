import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import App from './App.vue'
import { router } from './router'
import './styles/tokens.css'
import './styles/base.css'
import './styles/element.css'
import './styles/theme.css'
import './styles/print.css'
import { initTheme } from './composables/useTheme'

initTheme()
createApp(App).use(router).use(ElementPlus, { locale: zhCn }).mount('#app')
