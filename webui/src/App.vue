<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { listMobilePcs } from './api'
import DesktopWorkspace from './DesktopWorkspace.vue'
import MobileWorkspace from './mobile/MobileWorkspace.vue'
import PetDesktopView from './PetDesktopView.vue'
import PetPickerView from './PetPickerView.vue'

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
let mediaQuery: MediaQueryList | null = null

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
    document.title = name || 'AITools'
  } catch {
    document.title = 'AITools'
  }
}

onMounted(() => {
  mediaQuery = window.matchMedia(MOBILE_QUERY)
  syncViewportMode()
  mediaQuery.addEventListener('change', syncViewportMode)
  void syncDocumentTitle()
})

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener('change', syncViewportMode)
  mediaQuery = null
})
</script>

<template>
  <div class="app-shell">
    <PetDesktopView v-if="isPetView" />
    <PetPickerView v-else-if="isAskHereView" />
    <MobileWorkspace v-else-if="isMobile" />
    <DesktopWorkspace v-else />
  </div>
</template>
