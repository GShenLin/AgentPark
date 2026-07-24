<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { listMobilePcs, loadWorkspaceBootstrap, type WorkspaceBootstrap } from './api'
import UserInteractionDialog from './components/UserInteractionDialog.vue'
import WorkAlertToast from './components/WorkAlertToast.vue'
import { startAppEventStream } from './composables/useAppEventStream'
import { primeUserInteractions, useUserInteractions } from './composables/useUserInteractions'
import { initializeForegroundAlerts } from './composables/useWorkAlerts'
import DesktopWorkspace from './DesktopWorkspace.vue'
import MobileWorkspace from './mobile/MobileWorkspace.vue'
import MobileUserInteractionDrawer from './mobile/MobileUserInteractionDrawer.vue'
import PetDesktopView from './PetDesktopView.vue'
import PetPickerView from './PetPickerView.vue'
import { applyThemeConfig, applyWorkspaceTheme } from './theme'

const MOBILE_QUERY = '(max-width: 760px)'
const isPetView = ref(
  typeof window !== 'undefined'
    ? window.location.pathname === '/pet' || new URLSearchParams(window.location.search).get('pet') === '1'
    : false,
)
const isAskHereView = ref(
  typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search).get('ask_here') === '1'
    : false,
)
const isMobile = ref(typeof window !== 'undefined' ? window.matchMedia(MOBILE_QUERY).matches : false)
const workspaceBootstrap = ref<WorkspaceBootstrap | null>(null)
const bootstrapError = ref('')
let mediaQuery: MediaQueryList | null = null
let stopForegroundAlerts: (() => void) | null = null
let stopAppEventStream: (() => void) | null = null

function syncViewportMode() {
  if (!mediaQuery) return
  isMobile.value = mediaQuery.matches
}

async function syncDocumentTitle() {
  try {
    if (isPetView.value) {
      document.title = 'AgentPark Pet'
      return
    }
    if (isAskHereView.value) {
      document.title = 'AgentPark Ask Here'
      return
    }
    const pcs = await listMobilePcs()
    const name = String(pcs.find((pc) => pc.id === 'local')?.name || pcs[0]?.name || '').trim()
    document.title = name || 'AgentPark'
  } catch {
    document.title = 'AgentPark'
  }
}

onMounted(async () => {
  stopForegroundAlerts = initializeForegroundAlerts()
  mediaQuery = window.matchMedia(MOBILE_QUERY)
  syncViewportMode()
  mediaQuery.addEventListener('change', syncViewportMode)
  const desktopWorkspace = !isPetView.value && !isAskHereView.value && !isMobile.value
  try {
    if (desktopWorkspace) {
      const bootstrap = await loadWorkspaceBootstrap()
      workspaceBootstrap.value = bootstrap
      primeUserInteractions(bootstrap.user_interactions)
      applyThemeConfig(bootstrap.theme.data, bootstrap.theme.active_preset_id)
      const name = String(bootstrap.mobile_pcs.find((pc) => pc.id === 'local')?.name || '').trim()
      document.title = name || 'AgentPark'
    } else {
      await Promise.all([applyWorkspaceTheme(), syncDocumentTitle(), useUserInteractions().refreshRequests()])
    }
  } catch (error) {
    bootstrapError.value = error instanceof Error ? error.message : String(error)
  }
  stopAppEventStream = startAppEventStream()
})

onBeforeUnmount(() => {
  stopAppEventStream?.()
  stopAppEventStream = null
  stopForegroundAlerts?.()
  stopForegroundAlerts = null
  mediaQuery?.removeEventListener('change', syncViewportMode)
  mediaQuery = null
})
</script>

<template>
  <div class="app-shell">
    <PetDesktopView v-if="isPetView" />
    <PetPickerView v-else-if="isAskHereView" />
    <MobileWorkspace v-else-if="isMobile" />
    <DesktopWorkspace v-else-if="workspaceBootstrap" :bootstrap="workspaceBootstrap" />
    <div v-else class="workspace-bootstrap-status">
      {{ bootstrapError || 'Loading workspace…' }}
    </div>
    <MobileUserInteractionDrawer v-if="isMobile" />
    <UserInteractionDialog v-else global />
    <WorkAlertToast />
  </div>
</template>
