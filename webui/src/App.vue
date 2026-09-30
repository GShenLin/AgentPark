<script setup lang="ts">
import { inject, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { cloudBoardSession } from './portal/boardSession'
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
let accessGeneration = 0
const boardSession = inject(cloudBoardSession, null)
const unregisterBoardSession = boardSession?.register({
  suspend() { accessGeneration += 1; stopAppEventStream?.(); stopAppEventStream = null },
  async restore() {
    const generation = accessGeneration
    const status = await getAccessStatus()
    if (generation !== accessGeneration) throw new Error('访问校验已取消，请重新连接。')
    if (status.username_required) throw new Error('访问身份已失效，请重新打开设备并验证身份。')
    accessStatus.value = status
    if (workspaceBootstrap.value) workspaceBootstrap.value = { ...workspaceBootstrap.value, access: status }
    if (!accessReady.value) {
      if (!await mountWorkspace(generation)) throw new Error('页面初始化已取消，请重新连接。')
      accessReady.value = true
      bootstrapError.value = ''
      await nextTick()
    }
  },
  activate() { stopAppEventStream = startAppEventStream({ resync: true }) },
})

function syncViewportMode() {
  if (!mediaQuery) return
  isMobile.value = mediaQuery.matches
}

async function mountWorkspace(generation = accessGeneration) {
  // Bootstrap both layouts so changing viewport size can switch without reloading.
    const bootstrap = await loadWorkspaceBootstrap()
    if (generation !== accessGeneration) return false
    workspaceBootstrap.value = bootstrap
    accessStatus.value = bootstrap.access
    primeUserInteractions(bootstrap.user_interactions)
    applyThemeConfig(bootstrap.theme.data, bootstrap.theme.active_preset_id)
    const name = String(bootstrap.mobile_pcs.find((pc) => pc.id === 'local')?.name || '').trim()
    document.title = name || 'AgentPark'
  if (!boardSession || boardSession.phase.value === 'ready') stopAppEventStream = startAppEventStream()
  return true
}

async function initializeAccess() {
  const generation = accessGeneration
  accessBusy.value = true
  accessError.value = ''
  try {
    const status = await getAccessStatus()
    if (generation !== accessGeneration) return
    accessStatus.value = status
    if (status.username_required) {
      accessPromptOpen.value = true
      return
    }
    accessPromptOpen.value = false
    if (!await mountWorkspace(generation)) return
    accessReady.value = true
  } catch (error) {
    if (generation !== accessGeneration) return
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
  unregisterBoardSession?.()
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
