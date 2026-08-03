import { createApp } from 'vue'
import './style.css'
import 'katex/dist/katex.min.css'
import App from './App.vue'
import { initializeI18n } from './i18n'

initializeI18n()
createApp(App).mount('#app')
