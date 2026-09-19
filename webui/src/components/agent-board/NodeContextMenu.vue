<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { saveAgentProfileFromNode } from '../../api'
import ActionButton from '../ActionButton.vue'
import { t } from '../../i18n'
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
const duplicatingNode = ref(false)
const openingFolder = ref<'node' | 'work' | null>(null)
const changingPrivacy = ref(false)
const targetIsPrivate = computed(() => {
  const nodeId = String(targetNodeId.value || '').trim()
  return nodeId ? ctx.nodeConfigs.value[nodeId]?.private === true : false
})

const actionBusy = computed(
  () => duplicatingNode.value || openingFolder.value !== null || changingPrivacy.value,
)

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

async function openFolder(kind: 'node' | 'work') {
  const nodeId = String(targetNodeId.value || '').trim()
  if (!nodeId || openingFolder.value) return
  openingFolder.value = kind
  try {
    if (kind === 'node') {
      await ctx.openNodeFolder(nodeId)
    } else {
      await ctx.openWorkFolder(nodeId)
    }
    closeMenu()
  } finally {
    openingFolder.value = null
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

function renameNode() {
  const nodeId = String(targetNodeId.value || '').trim()
  if (!nodeId) return
  closeMenu()
  ctx.startNodeRename(nodeId)
}

async function duplicateNode() {
  const nodeId = String(targetNodeId.value || '').trim()
  if (!nodeId || duplicatingNode.value) return
  duplicatingNode.value = true
  try {
    await ctx.duplicateNodeCard(nodeId)
    closeMenu()
  } finally {
    duplicatingNode.value = false
  }
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

async function togglePrivacy() {
  const nodeId = String(targetNodeId.value || '').trim()
  if (!nodeId || changingPrivacy.value) return
  changingPrivacy.value = true
  try {
    await ctx.setNodePrivacy(nodeId, !targetIsPrivate.value)
    closeMenu()
  } finally {
    changingPrivacy.value = false
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
        <ActionButton variant="menu" :disabled="actionBusy" @click="renameNode">
          {{ t('board.renameNode') }}
        </ActionButton>
        <ActionButton variant="menu" :disabled="actionBusy" @click="duplicateNode">
          {{ t('board.duplicate') }}
        </ActionButton>
        <ActionButton variant="menu" :disabled="actionBusy" @click="openFolder('node')">
          {{ openingFolder === 'node' ? 'OpeningNodeFolder...' : 'OpenNodeFolder' }}
        </ActionButton>
        <ActionButton variant="menu" :disabled="actionBusy" @click="openFolder('work')">
          {{ openingFolder === 'work' ? 'OpeningWorkFolder...' : 'OpenWorkFolder' }}
        </ActionButton>
        <ActionButton variant="menu" :disabled="actionBusy" @click="saveToProfile">SaveToProfile</ActionButton>
        <ActionButton variant="menu" :disabled="actionBusy" @click="togglePrivacy">
          {{ changingPrivacy ? 'ChangingVisibility...' : (targetIsPrivate ? 'SetPublic' : 'SetPrivate') }}
        </ActionButton>
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
  border: 1px solid var(--theme-panel-node-context-menu-button-border, rgba(148, 163, 184, 0.22));
  background-color: var(--theme-panel-node-context-menu-background-color, rgba(2, 6, 23, 0.96));
  background-image: var(--theme-panel-node-context-menu-background-image, none);
  background-size: var(--theme-panel-node-context-menu-background-size, cover);
  background-position: var(--theme-panel-node-context-menu-background-position, center);
  background-repeat: var(--theme-panel-node-context-menu-background-repeat, no-repeat);
  background-blend-mode: var(--theme-panel-node-context-menu-background-blend-mode, normal);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.42);
  --ui-button-text: var(--theme-panel-node-context-menu-button-text, rgba(226, 232, 240, 0.96));
  --ui-button-hover-background: var(--theme-panel-node-context-menu-button-hover-background, rgba(14, 116, 144, 0.28));
}
</style>

