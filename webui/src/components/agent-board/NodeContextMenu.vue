<script setup lang="ts">
import { inject, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { launchNodeDesktopPet, saveAgentProfileFromNode } from '../../api'
import { AgentBoardKey } from './context'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected

const menuEl = ref<HTMLElement | null>(null)
const showMenu = ref(false)
const menuLeft = ref(0)
const menuTop = ref(0)
const targetNodeId = ref('')
const launchingPet = ref(false)

function closeMenu() {
  showMenu.value = false
  targetNodeId.value = ''
}

function updateMenuPosition() {
  const menu = menuEl.value
  if (!menu) return
  const width = menu.offsetWidth || 180
  const height = menu.offsetHeight || 72
  const margin = 12
  menuLeft.value = Math.max(margin, Math.min(menuLeft.value, window.innerWidth - width - margin))
  menuTop.value = Math.max(margin, Math.min(menuTop.value, window.innerHeight - height - margin))
}

async function showPet() {
  const nodeId = String(targetNodeId.value || '').trim()
  if (!nodeId || launchingPet.value) return
  const node = ctx.nodes.value.find((item) => item.id === nodeId)
  launchingPet.value = true
  ctx.lastError.value = null
  try {
    await launchNodeDesktopPet({
      graph_id: ctx.currentGraphId.value || 'default',
      node_id: nodeId,
      working_path: String(node?.workingPath || '').trim() || undefined,
      visible: true,
      pinned: true,
    })
    closeMenu()
  } catch (error: any) {
    ctx.lastError.value = String(error?.message || error)
  } finally {
    launchingPet.value = false
  }
}

function openAt(screenPoint: { x: number; y: number }, nodeId: string) {
  const safeNodeId = String(nodeId || '').trim()
  if (!safeNodeId) return
  targetNodeId.value = safeNodeId
  menuLeft.value = Number(screenPoint?.x ?? 0)
  menuTop.value = Number(screenPoint?.y ?? 0)
  showMenu.value = true
  void nextTick(updateMenuPosition)
}

async function saveToProfile() {
  const nodeId = String(targetNodeId.value || '').trim()
  if (!nodeId) return
  const node = ctx.nodes.value.find((item) => item.id === nodeId)
  const defaultId = String(node?.name || nodeId).trim().replace(/[^A-Za-z0-9_-]/g, '_') || nodeId
  const profileId = String(window.prompt('Profile ID', defaultId) || '').trim()
  if (!profileId) return
  const profileName = String(window.prompt('Profile name', node?.name || profileId) || '').trim() || profileId
  ctx.lastError.value = null
  try {
    await saveAgentProfileFromNode({
      graph_id: ctx.currentGraphId.value || 'default',
      node_id: nodeId,
      profile_id: profileId,
      profile_name: profileName,
    })
    window.dispatchEvent(new CustomEvent('agent-profiles-changed'))
    closeMenu()
  } catch (error: any) {
    ctx.lastError.value = String(error?.message || error)
  }
}

function onWindowKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeMenu()
}

onMounted(() => {
  window.addEventListener('keydown', onWindowKeyDown)
  window.addEventListener('resize', updateMenuPosition)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeyDown)
  window.removeEventListener('resize', updateMenuPosition)
})

defineExpose({
  openAt,
  closeMenu,
})
</script>

<template>
  <Teleport to="body">
    <div v-if="showMenu" class="node-menu-overlay" @pointerdown="closeMenu" @contextmenu.prevent="closeMenu">
      <section
        ref="menuEl"
        class="node-menu"
        :style="{ left: `${menuLeft}px`, top: `${menuTop}px` }"
        @pointerdown.stop
        @contextmenu.prevent
      >
        <button class="node-menu-item" :disabled="launchingPet" @click="showPet">
          {{ launchingPet ? 'ShowingPet...' : 'ShowPet' }}
        </button>
        <button class="node-menu-item" :disabled="launchingPet" @click="saveToProfile">SaveToProfile</button>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.node-menu-overlay {
  position: fixed;
  inset: 0;
  z-index: 1150;
}

.node-menu {
  position: fixed;
  min-width: 180px;
  padding: 6px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(2, 6, 23, 0.96);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.42);
}

.node-menu-item {
  width: 100%;
  text-align: left;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: rgba(226, 232, 240, 0.96);
  font-size: 12px;
  padding: 8px 10px;
  cursor: pointer;
}

.node-menu-item:disabled {
  cursor: progress;
  opacity: 0.58;
}

.node-menu-item:hover {
  background: rgba(14, 116, 144, 0.28);
}
</style>

