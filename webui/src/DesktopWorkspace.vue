<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import {
  getStartupGraphConfig,
  getRemoteStatus,
  listProviders,
  listTools,
  loadGraph,
} from './api'
import { useGlobalState } from './composables/useGlobalState'
import { useMemory } from './composables/useMemory'
import FileExplorer from './components/FileExplorer.vue'
import AgentBoard from './components/AgentBoard.vue'
import MemoryPanel from './components/MemoryPanel.vue'
import SettingsPage from './components/SettingsPage.vue'
import DesktopTopbar from './components/DesktopTopbar.vue'
import { AgentBoardKey } from './components/agent-board/context'
import { useAgentBoard } from './components/agent-board/useAgentBoard'

const {
  lastError,
  graphLoadRequest,
  currentGraphId,
  currentGraphName,
  currentGraphWorkingPath,
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
const canAccessLocalFiles = ref(true)
const fileExplorerRootPath = ref('')
const activeView = ref<'board' | 'settings'>('board')

const leftWidth = computed(() => (leftCollapsed.value ? 44 : leftSidebarWidth.value))
const rightWidth = computed(() => (rightCollapsed.value ? 44 : memoryPanelWidth.value))

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
  if (!canAccessLocalFiles.value) return
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
  if (!canAccessLocalFiles.value) return
  leftCollapsed.value = !leftCollapsed.value
}

function toggleRightPanel() {
  rightCollapsed.value = !rightCollapsed.value
}

async function refreshProviders() {
  providers.value = await listProviders()
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
    const remoteStatus = await getRemoteStatus()
    canAccessLocalFiles.value = remoteStatus.is_local_client === true
    await refreshProviders()
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
    currentGraphWorkingPath.value = String((targetGraph as any)?.working_path || '').trim()
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
  () => [agentBoard.selectedNodeWorkingPathRevision.value, currentGraphWorkingPath.value],
  () => {
    fileExplorerRootPath.value = String(agentBoard.selectedNodeWorkingPath.value || currentGraphWorkingPath.value || '').trim()
  },
)
</script>

<template>
  <div class="desktop-workspace">
    <DesktopTopbar
      v-model:active-view="activeView"
      :left-collapsed="leftCollapsed"
      :right-collapsed="rightCollapsed"
      :can-access-local-files="canAccessLocalFiles"
      @toggle-left="toggleLeftSidebar"
      @toggle-right="toggleRightPanel"
      @error="lastError = $event || null"
    />

    <SettingsPage v-if="activeView === 'settings'" @back="activeView = 'board'" @providers-updated="refreshProviders" />

    <div v-else class="content">
      <aside v-if="canAccessLocalFiles" class="left-sidebar" :class="{ collapsed: leftCollapsed }" :style="{ width: `${leftWidth}px` }">
        <FileExplorer v-if="!leftCollapsed" :root-path="fileExplorerRootPath" @file-selected="onFileSelected" />
        <div v-else class="collapsed-mark">Files</div>
      </aside>
      <div v-if="canAccessLocalFiles" class="sidebar-resizer" @mousedown="startLeftResize"></div>

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

/* 左侧文件浏览器 */
.left-sidebar {
  width: 280px;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  border-right: 1px solid var(--border-subtle);
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
  font-weight: 500;
  color: var(--text-tertiary);
  text-transform: uppercase;
  user-select: none;
}

/* 调整分隔条 - 视觉细但拖拽区域大 */
.sidebar-resizer {
  width: 3px;
  cursor: col-resize;
  background: var(--border-subtle);
  transition: background 0.15s ease;
  flex-shrink: 0;
  position: relative;
}

.sidebar-resizer::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: -8px;
  right: -8px;
  background: transparent;
}

.sidebar-resizer:hover,
.sidebar-resizer:active {
  background: var(--accent-blue);
}

.memory-resizer {
  width: 3px;
  cursor: col-resize;
  background: var(--border-subtle);
  transition: background 0.15s ease;
  flex-shrink: 0;
  z-index: 10;
  position: relative;
}

.memory-resizer::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: -8px;
  right: -8px;
  background: transparent;
}

.memory-resizer:hover,
.memory-resizer:active {
  background: var(--accent-blue);
}

/* 右侧记忆面板 */
.right {
  width: 560px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-primary);
}
</style>
