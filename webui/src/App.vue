<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getAccessStatus, loadWorkspaceBootstrap, type AccessStatus, type WorkspaceBootstrap } from './api'
import { setAccessUsername } from './accessIdentity'
import AccessUsernameDialog from './components/AccessUsernameDialog.vue'
import UserInteractionDialog from './components/UserInteractionDialog.vue'
import WorkAlertToast from './components/WorkAlertToast.vue'
import { startAppEventStream } from './composables/useAppEventStream'
import { primeUserInteractions } from './composables/useUserInteractions'
import { initializeForegroundAlerts } from './composables/useWorkAlerts'
import DesktopWorkspace from './DesktopWorkspace.vue'
import MobileWorkspace from './mobile/MobileWorkspace.vue'
import MobileUserInteractionDrawer from './mobile/MobileUserInteractionDrawer.vue'
import { applyThemeConfig } from './theme'
import { t } from './i18n'

const MOBILE_QUERY = '(max-width: 760px)'
const isMobile = ref(typeof window !== 'undefined' ? window.matchMedia(MOBILE_QUERY).matches : false)
const workspaceBootstrap = ref<WorkspaceBootstrap | null>(null)
const accessStatus = ref<AccessStatus | null>(null)
const accessReady = ref(false)
const accessPromptOpen = ref(false)
const accessBusy = ref(false)
const accessError = ref('')
const bootstrapError = ref('')
let mediaQuery: MediaQueryList | null = null
let stopForegroundAlerts: (() => void) | null = null
let stopAppEventStream: (() => void) | null = null

function syncViewportMode() {
  if (!mediaQuery) return
  isMobile.value = mediaQuery.matches
}

async function mountWorkspace() {
  // Bootstrap both layouts so changing viewport size can switch without reloading.
    const bootstrap = await loadWorkspaceBootstrap()
    workspaceBootstrap.value = bootstrap
    accessStatus.value = bootstrap.access
    primeUserInteractions(bootstrap.user_interactions)
    applyThemeConfig(bootstrap.theme.data, bootstrap.theme.active_preset_id)
    const name = String(bootstrap.mobile_pcs.find((pc) => pc.id === 'local')?.name || '').trim()
    document.title = name || 'AgentPark'
  stopAppEventStream = startAppEventStream()
}

async function initializeAccess() {
  accessBusy.value = true
  accessError.value = ''
  try {
    const status = await getAccessStatus()
    accessStatus.value = status
    if (status.username_required) {
      accessPromptOpen.value = true
      return
    }
    accessPromptOpen.value = false
    await mountWorkspace()
    accessReady.value = true
  } catch (error) {
    accessError.value = error instanceof Error ? error.message : String(error)
    bootstrapError.value = accessError.value
  } finally {
    accessBusy.value = false
  }
}

async function submitAccessUsername(username: string) {
  setAccessUsername(username)
  await initializeAccess()
}

onMounted(async () => {
  stopForegroundAlerts = initializeForegroundAlerts()
  mediaQuery = window.matchMedia(MOBILE_QUERY)
  syncViewportMode()
  mediaQuery.addEventListener('change', syncViewportMode)
  await initializeAccess()
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
    <AccessUsernameDialog
      v-if="accessPromptOpen"
      :busy="accessBusy"
      :error="accessError"
      @submit="submitAccessUsername"
    />
    <MobileWorkspace v-else-if="accessReady && isMobile && accessStatus" :access="accessStatus" />
    <DesktopWorkspace v-else-if="workspaceBootstrap" :bootstrap="workspaceBootstrap" />
    <div v-else class="workspace-bootstrap-status">
      {{ bootstrapError || t('app.loadingWorkspace') }}
    </div>
    <MobileUserInteractionDrawer v-if="isMobile" />
    <UserInteractionDialog v-else global />
    <WorkAlertToast />
  </div>
</template>
