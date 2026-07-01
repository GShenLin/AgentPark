<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { listMobilePcs } from './api'
import DesktopWorkspace from './DesktopWorkspace.vue'
import MobileWorkspace from './mobile/MobileWorkspace.vue'

const MOBILE_QUERY = '(max-width: 760px)'
const isMobile = ref(typeof window !== 'undefined' ? window.matchMedia(MOBILE_QUERY).matches : false)
let mediaQuery: MediaQueryList | null = null

function syncViewportMode() {
  if (!mediaQuery) return
  isMobile.value = mediaQuery.matches
}

async function syncDocumentTitle() {
  try {
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
    <MobileWorkspace v-if="isMobile" />
    <DesktopWorkspace v-else />
  </div>
</template>
