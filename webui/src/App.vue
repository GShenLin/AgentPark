<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getWebuiCloseSignal } from './api'
import DesktopWorkspace from './DesktopWorkspace.vue'
import MobileWorkspace from './mobile/MobileWorkspace.vue'

const MOBILE_QUERY = '(max-width: 760px)'
const isMobile = ref(typeof window !== 'undefined' ? window.matchMedia(MOBILE_QUERY).matches : false)
let mediaQuery: MediaQueryList | null = null
let closePollTimer: number | null = null
let lastCloseToken = ''

function syncViewportMode() {
  if (!mediaQuery) return
  isMobile.value = mediaQuery.matches
}

onMounted(() => {
  mediaQuery = window.matchMedia(MOBILE_QUERY)
  syncViewportMode()
  mediaQuery.addEventListener('change', syncViewportMode)
  closePollTimer = window.setInterval(async () => {
    try {
      const signal = await getWebuiCloseSignal()
      const token = String(signal?.token || '')
      if (!signal?.close || !token || token === lastCloseToken) return
      lastCloseToken = token
      window.open('', '_self')
      window.close()
    } catch {
      // The backend may be stopping during restart; ignore transient failures.
    }
  }, 1000)
})

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener('change', syncViewportMode)
  mediaQuery = null
  if (closePollTimer !== null) {
    window.clearInterval(closePollTimer)
    closePollTimer = null
  }
})
</script>

<template>
  <div class="app-shell">
    <MobileWorkspace v-if="isMobile" />
    <DesktopWorkspace v-else />
  </div>
</template>
