<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import {
  addRemote,
  deleteRemote,
  getStartupGraphConfig,
  listProviders,
  listRemotes,
  listTools,
  loadGraph,
  restartServer,
} from './api'
import { useGlobalState } from './composables/useGlobalState'
import { useMemory } from './composables/useMemory'
import FileExplorer from './components/FileExplorer.vue'
import AgentBoard from './components/AgentBoard.vue'
import MemoryPanel from './components/MemoryPanel.vue'
import { AgentBoardKey } from './components/agent-board/context'
import { useAgentBoard } from './components/agent-board/useAgentBoard'
import type { RemoteEndpoint } from './apiTypes'

const {
  lastError,
  graphLoadRequest,
  currentGraphId,
  currentGraphName,
  selectedNodeId,
  memoryMode,
  providers,
  availableTools,
} = useGlobalState()
const { onFileSelected } = useMemory()

const agentBoard = useAgentBoard()
provide(AgentBoardKey, agentBoard)

const LEFT_WIDTH_KEY = 'aitools.leftSidebarWidth'
const RIGHT_WIDTH_KEY = 'aitools.rightPanelWidth'
const LEFT_COLLAPSED_KEY = 'aitools.leftCollapsed'
const RIGHT_COLLAPSED_KEY = 'aitools.rightCollapsed'

function readStoredNumber(key: string, fallback: number, min: number, max: number) {
  try {
    const raw = Number(window.localStorage.getItem(key))
    if (Number.isFinite(raw)) {
      return Math.max(min, Math.min(max, raw))
    }
  } catch {
    // ignore local storage errors
  }
  return fallback
}

function readStoredBoolean(key: string, fallback = false) {
  try {
    const raw = window.localStorage.getItem(key)
    if (raw == null) return fallback
    return raw === '1'
  } catch {
    return fallback
  }
}

const memoryPanelWidth = ref(560)
const isResizingMemory = ref(false)
const leftSidebarWidth = ref(280)
const isResizingLeft = ref(false)
const leftCollapsed = ref(false)
const rightCollapsed = ref(false)

const leftWidth = computed(() => (leftCollapsed.value ? 44 : leftSidebarWidth.value))
const rightWidth = computed(() => (rightCollapsed.value ? 44 : memoryPanelWidth.value))
const fileExplorerRootPath = ref('')
const remoteEndpoints = ref<RemoteEndpoint[]>([])
const selectedRemoteId = ref('default')
const showRemoteForm = ref(false)
const remoteFormName = ref('')
const remoteFormHost = ref('')
const remoteFormPort = ref('8788')
const isRestarting = ref(false)

const selectedRemote = computed(() => {
  return remoteEndpoints.value.find((remote) => remote.id === selectedRemoteId.value) || remoteEndpoints.value[0] || null
})

const selectedRemoteAddress = computed(() => {
  const remote = selectedRemote.value
  if (!remote) return '127.0.0.1:8788'
  return `${remote.host}:${remote.port}`
})

const modeLabel = computed(() => {
  if (memoryMode.value === 'agent') return 'Node Memory'
  if (memoryMode.value === 'file') return 'File'
  if (memoryMode.value === 'graph') return 'Graph'
  return 'Node Memory'
})

const selectedLabel = computed(() => String(selectedNodeId.value || '').trim() || 'none')

function startMemoryResize(event: MouseEvent) {
  if (rightCollapsed.value) return
  if (event.button !== 0) return
  isResizingMemory.value = true
  event.preventDefault()
}

function stopMemoryResize() {
  isResizingMemory.value = false
}

function handleMemoryResize(event: MouseEvent) {
  if (!isResizingMemory.value) return
  const content = document.querySelector('.content') as HTMLElement | null
  if (!content) return
  const rect = content.getBoundingClientRect()
  const maxWidth = Math.max(360, rect.width - 320)
  const nextWidth = rect.right - event.clientX
  memoryPanelWidth.value = Math.max(360, Math.min(maxWidth, nextWidth))
}

function startLeftResize(event: MouseEvent) {
  if (leftCollapsed.value) return
  if (event.button !== 0) return
  isResizingLeft.value = true
  event.preventDefault()
}

function stopLeftResize() {
  isResizingLeft.value = false
}

function handleLeftResize(event: MouseEvent) {
  if (!isResizingLeft.value) return
  const nextWidth = event.clientX
  leftSidebarWidth.value = Math.max(160, Math.min(600, nextWidth))
}

function toggleLeftSidebar() {
  leftCollapsed.value = !leftCollapsed.value
}

function toggleRightPanel() {
  rightCollapsed.value = !rightCollapsed.value
}

function remoteBaseUrl(remote: RemoteEndpoint) {
  return `http://${remote.host}:${remote.port}`
}

async function refreshRemotes() {
  remoteEndpoints.value = await listRemotes()
  if (!remoteEndpoints.value.some((remote) => remote.id === selectedRemoteId.value)) {
    selectedRemoteId.value = remoteEndpoints.value[0]?.id || 'default'
  }
}

function selectRemote() {
  const remote = selectedRemote.value
  if (!remote) return
  if (remote.id === 'default') return
  window.open(remoteBaseUrl(remote), '_blank', 'noopener,noreferrer')
}

async function submitRemote() {
  const name = remoteFormName.value.trim()
  const host = remoteFormHost.value.trim()
  const port = remoteFormPort.value.trim()
  if (!name || !host || !port) {
    lastError.value = 'Remote name, IP/host, and port are required.'
    return
  }
  try {
    const res = await addRemote({ name, host, port })
    remoteEndpoints.value = res.remotes
    showRemoteForm.value = false
    remoteFormName.value = ''
    remoteFormHost.value = ''
    remoteFormPort.value = '8788'
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
}

async function removeSelectedRemote() {
  const remote = selectedRemote.value
  if (!remote || remote.id === 'default') return
  try {
    const res = await deleteRemote(remote.id)
    remoteEndpoints.value = res.remotes
    selectedRemoteId.value = 'default'
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
}

async function restartWorkspace() {
  if (isRestarting.value) return
  isRestarting.value = true
  lastError.value = ''
  try {
    await restartServer()
  } catch (e: any) {
    lastError.value = String(e?.message || e)
    isRestarting.value = false
  }
}

onMounted(async () => {
  selectedNodeId.value = null
  memoryMode.value = 'graph'

  leftSidebarWidth.value = readStoredNumber(LEFT_WIDTH_KEY, 280, 160, 600)
  memoryPanelWidth.value = readStoredNumber(RIGHT_WIDTH_KEY, 560, 360, 980)
  leftCollapsed.value = readStoredBoolean(LEFT_COLLAPSED_KEY, false)
  rightCollapsed.value = readStoredBoolean(RIGHT_COLLAPSED_KEY, false)

  window.addEventListener('mousemove', handleMemoryResize)
  window.addEventListener('mousemove', handleLeftResize)
  window.addEventListener('mouseup', stopMemoryResize)
  window.addEventListener('mouseup', stopLeftResize)

  try {
    await refreshRemotes()
    providers.value = await listProviders()
    availableTools.value = await listTools()
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
  try {
    const startup = await getStartupGraphConfig().catch(() => ({ graph_id: 'default', graph_name: 'default' }))
    const targetId = String(startup?.graph_id || 'default').trim() || 'default'
    const targetGraph = await loadGraph(targetId)

    const resolvedId = String(targetGraph?.id || 'default')
    currentGraphId.value = resolvedId
    currentGraphName.value = String(targetGraph?.name || resolvedId)
    graphLoadRequest.value = targetGraph
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('mousemove', handleMemoryResize)
  window.removeEventListener('mousemove', handleLeftResize)
  window.removeEventListener('mouseup', stopMemoryResize)
  window.removeEventListener('mouseup', stopLeftResize)
})

watch(leftSidebarWidth, (value) => {
  try {
    window.localStorage.setItem(LEFT_WIDTH_KEY, String(value))
  } catch {
    // ignore local storage errors
  }
})

watch(memoryPanelWidth, (value) => {
  try {
    window.localStorage.setItem(RIGHT_WIDTH_KEY, String(value))
  } catch {
    // ignore local storage errors
  }
})

watch(leftCollapsed, (value) => {
  try {
    window.localStorage.setItem(LEFT_COLLAPSED_KEY, value ? '1' : '0')
  } catch {
    // ignore local storage errors
  }
})

watch(rightCollapsed, (value) => {
  try {
    window.localStorage.setItem(RIGHT_COLLAPSED_KEY, value ? '1' : '0')
  } catch {
    // ignore local storage errors
  }
})

watch(
  () => agentBoard.selectedNodeWorkingPathRevision.value,
  () => {
    fileExplorerRootPath.value = String(agentBoard.selectedNodeWorkingPath.value || '').trim()
  },
)
</script>

<template>
  <div class="desktop-workspace">
    <header class="topbar">
      <div class="brand">AITools Board</div>
      <div class="remote-switcher">
        <span class="remote-label">Remote</span>
        <select v-model="selectedRemoteId" class="remote-select" @change="selectRemote">
          <option v-for="remote in remoteEndpoints" :key="remote.id" :value="remote.id">
            {{ remote.name }} · {{ remote.host }}:{{ remote.port }}
          </option>
        </select>
        <span class="remote-address">{{ selectedRemoteAddress }}</span>
        <button class="topbar-btn" type="button" @click="showRemoteForm = !showRemoteForm">Add</button>
        <button class="topbar-btn danger" type="button" :disabled="selectedRemoteId === 'default'" @click="removeSelectedRemote">Delete</button>
      </div>
      <form v-if="showRemoteForm" class="remote-form" @submit.prevent="submitRemote" @click.stop>
        <input v-model="remoteFormName" class="remote-input" placeholder="Name" />
        <input v-model="remoteFormHost" class="remote-input" placeholder="IP / Host" />
        <input v-model="remoteFormPort" class="remote-input port" placeholder="Port" />
        <button class="topbar-btn primary" type="submit">Save</button>
      </form>
      <div class="topbar-meta">
        <span class="chip">Graph: {{ currentGraphName || currentGraphId || 'default' }}</span>
        <span class="chip">Mode: {{ modeLabel }}</span>
        <span class="chip">Selected: {{ selectedLabel }}</span>
      </div>
      <div class="topbar-actions">
        <button class="topbar-btn restart" type="button" :disabled="isRestarting" @click="restartWorkspace">
          {{ isRestarting ? 'Restarting...' : 'Restart' }}
        </button>
        <button class="topbar-btn" type="button" @click="toggleLeftSidebar">
          {{ leftCollapsed ? 'Show Files' : 'Hide Files' }}
        </button>
        <button class="topbar-btn" type="button" @click="toggleRightPanel">
          {{ rightCollapsed ? 'Show Memory' : 'Hide Memory' }}
        </button>
      </div>
    </header>

    <div class="content">
      <aside class="left-sidebar" :class="{ collapsed: leftCollapsed }" :style="{ width: `${leftWidth}px` }">
        <FileExplorer v-if="!leftCollapsed" :root-path="fileExplorerRootPath" @file-selected="onFileSelected" />
        <div v-else class="collapsed-mark">Files</div>
      </aside>
      <div class="sidebar-resizer" @mousedown="startLeftResize"></div>

      <div class="center">
        <main class="agent-stage">
          <AgentBoard />
          <div v-if="lastError" class="error">{{ lastError }}</div>
        </main>
      </div>

      <div class="memory-resizer" @mousedown="startMemoryResize"></div>
      <aside class="right" :class="{ collapsed: rightCollapsed }" :style="{ width: `${rightWidth}px` }">
        <MemoryPanel v-if="!rightCollapsed" />
        <div v-else class="collapsed-mark">Memory</div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.desktop-workspace {
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
}

.topbar {
  position: relative;
  z-index: 2000;
  overflow: visible;
}

.left-sidebar {
  width: 280px;
  display: flex;
  flex-direction: column;
  background: rgba(11, 15, 23, 0.62);
  border-right: 1px solid rgba(148, 163, 184, 0.15);
  overflow: hidden;
}

.left-sidebar.collapsed,
.right.collapsed {
  align-items: center;
  justify-content: center;
}

.collapsed-mark {
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  letter-spacing: 2px;
  font-size: 11px;
  color: rgba(148, 163, 184, 0.85);
  text-transform: uppercase;
}

.sidebar-resizer {
  width: 6px;
  cursor: col-resize;
  background: rgba(148, 163, 184, 0.08);
  transition: background 0.2s;
  flex-shrink: 0;
}

.sidebar-resizer:hover,
.sidebar-resizer:active {
  background: rgba(125, 211, 252, 0.5);
}

.memory-resizer {
  width: 6px;
  cursor: col-resize;
  background: rgba(148, 163, 184, 0.08);
  border-left: 1px solid rgba(148, 163, 184, 0.1);
  transition: background-color 0.2s;
  flex-shrink: 0;
  z-index: 10;
}

.memory-resizer:hover,
.memory-resizer:active {
  background: rgba(125, 211, 252, 0.3);
}

.right {
  width: 560px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.remote-switcher,
.remote-form {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.remote-form {
  position: absolute;
  left: 360px;
  top: 48px;
  z-index: 30;
  padding: 8px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(2, 6, 23, 0.94);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.28);
}

.remote-label,
.remote-address {
  color: rgba(148, 163, 184, 0.88);
  font-size: 11px;
  white-space: nowrap;
}

.remote-select,
.remote-input {
  min-width: 120px;
  max-width: 220px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: rgba(15, 23, 42, 0.7);
  color: rgba(226, 232, 240, 0.95);
  font-size: 12px;
  padding: 0 9px;
}

.remote-input.port {
  width: 74px;
  min-width: 74px;
}

.topbar-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.chip {
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: rgba(15, 23, 42, 0.5);
  color: rgba(226, 232, 240, 0.92);
  border-radius: 999px;
  font-size: 11px;
  padding: 3px 10px;
  white-space: nowrap;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.topbar-actions {
  display: flex;
  gap: 8px;
}

.topbar-btn {
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.25);
  color: rgba(226, 232, 240, 0.92);
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 8px;
}

.topbar-btn.primary {
  border-color: rgba(56, 189, 248, 0.45);
  color: rgba(186, 230, 253, 0.98);
}

.topbar-btn.danger {
  border-color: rgba(248, 113, 113, 0.35);
  color: rgba(254, 202, 202, 0.95);
}

.topbar-btn.restart {
  border-color: rgba(251, 191, 36, 0.4);
  color: rgba(254, 240, 138, 0.98);
}

.topbar-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

@media (max-width: 1280px) {
  .chip {
    max-width: 190px;
  }

  .topbar-btn {
    padding: 6px 8px;
    font-size: 11px;
  }
}
</style>
