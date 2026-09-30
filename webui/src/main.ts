import { createApp } from 'vue'
import './style.css'
import './styles/settingsSplit.css'
import './styles/workspaceLight.css'
import './styles/chatAppearance.css'
import 'katex/dist/katex.min.css'
import App from './App.vue'
import PortalRoot from './portal/PortalRoot.vue'
import { isCloudPortal } from './portal/environment'
import { initializeI18n } from './i18n'

initializeI18n()
createApp(isCloudPortal() ? PortalRoot : App).mount('#app')
