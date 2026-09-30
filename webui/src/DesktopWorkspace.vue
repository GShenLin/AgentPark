<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import {
  listProviders,
  loadGraph,
  setStartupGraphConfig,
  type WorkspaceBootstrap,
} from './api'
import { useGlobalState } from './composables/useGlobalState'
import { useMemory } from './composables/useMemory'
import { useDeletionUndo } from './composables/useDeletionUndo'
import { useWorkAlerts } from './composables/useWorkAlerts'
import FileExplorer from './components/FileExplorer.vue'
import AgentBoard from './components/AgentBoard.vue'
import AppErrorToast from './components/AppErrorToast.vue'
import MemoryPanel from './components/MemoryPanel.vue'
import ConversationWindow from './components/ConversationWindow.vue'
import { conversationWindowSettings } from './components/conversationWindowSettings'
import SettingsPage from './components/SettingsPage.vue'
import DesktopTopbar from './components/DesktopTopbar.vue'
import { AgentBoardKey } from './components/agent-board/context'
import NodeConfigDock from './components/agent-board/NodeConfigDock.vue'
import NodeInputDock from './components/agent-board/NodeInputDock.vue'
import { useAgentBoard } from './components/agent-board/useAgentBoard'
import { t } from './i18n'
import { normalizeAgentPanelSettings } from './agentPanelSettings'
import { resolveWorkspaceEscapeAction } from './workspaceKeyboard'

const props = defineProps<{ bootstrap: WorkspaceBootstrap }>()

const {
  lastError,
  graphLoadRequest,
  graphNodeFocusRequest,
  currentGraphId,
  currentGraphName,
  currentGraphWorkingPath,
  selectedNodeId,
  memoryMode,
  providers,
  availableTools,
} = useGlobalState()
const { onFileSelected } = useMemory()
const { navigationRequest, completeWorkAlertNavigation } = useWorkAlerts()

const workspaceMounted = ref(false)
const workspaceReady = ref(false)
const agentBoard = useAgentBoard({
  ready: workspaceReady,
  initialNodes: props.bootstrap.nodes,
  boardLayoutDefaults: props.bootstrap.board_layout,
})
provide(AgentBoardKey, agentBoard)
const { undoLastDeletion } = useDeletionUndo()

const LEFT_WIDTH_KEY = 'agentpark.leftSidebarWidth'
const RIGHT_MEMORY_WIDTH_KEY = 'agentpark.rightPanelWidth.memory'
const RIGHT_GRAPH_WIDTH_KEY = 'agentpark.rightPanelWidth.graph'
const LEGACY_RIGHT_WIDTH_KEY = 'agentpark.rightPanelWidth'
const LEFT_COLLAPSED_KEY = 'agentpark.leftCollapsed.defaultHidden'
const GRAPH_COLLAPSED_KEY = 'agentpark.rightCollapsed'

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
const graphPanelWidth = ref(560)
const isResizingMemory = ref(false)
const leftSidebarWidth = ref(280)
const isResizingLeft = ref(false)
const leftCollapsed = ref(false)
const graphCollapsed = ref(false)
const memoryOverlayOpen = ref(false)
const isLocalClient = ref(false)
const canAccessLocalFiles = computed(() => isLocalClient.value)
const isDeveloper = computed(() => props.bootstrap.access.is_developer === true)
const fileExplorerRootPath = ref('')
const activeView = ref<'board' | 'settings'>('board')
const settingsPageRef = ref<{ requestBack: () => void } | null>(null)
let graphNavigationVersion = 0

const leftWidth = computed(() => (leftCollapsed.value ? 44 : leftSidebarWidth.value))
const activeRightPanelWidth = computed({
  get() {
    return memoryMode.value === 'graph' ? graphPanelWidth.value : memoryPanelWidth.value
  },
  set(value: number) {
    if (memoryMode.value === 'graph') {
      graphPanelWidth.value = value
    } else {
      memoryPanelWidth.value = value
    }
  },
})
const rightWidth = computed(() => (graphCollapsed.value ? 44 : activeRightPanelWidth.value))
const isMemoryFloating = computed(() => memoryOverlayOpen.value)
const boardRightWidth = computed(() => (isMemoryFloating.value ? 0 : rightWidth.value))
const agentPanelSettings = ref(props.bootstrap.agent_panel)
provide(conversationWindowSettings, agentPanelSettings)
const rightPanelStyle = computed(() => isMemoryFloating.value ? {} : { width: `${rightWidth.value}px` })

function applyDefaultSettings(value: Record<string, unknown>) {
  agentPanelSettings.value = normalizeAgentPanelSettings(value.agentPanel)
  agentBoard.applyBoardLayoutDefaults(value)
}

function startMemoryResize(event: MouseEvent) {
  if (graphCollapsed.value) return
  if (event.button !== 0) return
  isResizingMemory.value = true
  event.preventDefault()
}

function stopMemoryResize() {
  isResizingMemory.value = false
}

function isEditableTarget(target: EventTarget | null) {
  return target instanceof HTMLElement && !!target.closest('input, textarea, [contenteditable="true"], select')
}

function onUndoKeyDown(event: KeyboardEvent) {
  if (isEditableTarget(event.target)) return
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return
  if (event.key.toLowerCase() !== 'z') return
  event.preventDefault()
  lastError.value = null
  void undoLastDeletion()
    .then(async (restored) => {
      if (!restored) return
      const graphId = String(restored.result.graph_id || '').trim()
      if (restored.result.kind === 'delete_graph') {
        currentGraphId.value = graphId || currentGraphId.value
        currentGraphName.value = graphId || currentGraphName.value
        graphLoadRequest.value = await loadGraph(graphId)
      } else if (graphId === (currentGraphId.value || 'default')) {
        await agentBoard.refreshNodeConfigsAndMemory()
        if (restored.result.kind === 'delete_node' && restored.result.node_id) {
          await agentBoard.selectAndFocusNode(restored.result.node_id).catch(() => false)
        }
      }
    })
    .catch((error: any) => {
      lastError.value = `Undo failed: ${String(error?.message || error)}`
    })
}

function hasBlockingDialogForWorkspaceEscape() {
  return Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]'))
    .some((dialog) => dialog.getClientRects().length > 0)
}

function onWorkspaceKeyDown(event: KeyboardEvent) {
  const escapeAction = resolveWorkspaceEscapeAction(event, {
    activeView: activeView.value,
    hasBlockingDialog: event.key === 'Escape' && hasBlockingDialogForWorkspaceEscape(),
  })
  if (escapeAction === 'settings-back') {
    event.preventDefault()
    settingsPageRef.value?.requestBack()
    return
  }
  onUndoKeyDown(event)
}

function handleMemoryResize(event: MouseEvent) {
  if (!isResizingMemory.value) return
  const content = document.querySelector('.content') as HTMLElement | null
  if (!content) return
  const rect = content.getBoundingClientRect()
  const maxWidth = Math.max(360, rect.width - 320)
  const nextWidth = rect.right - event.clientX
  activeRightPanelWidth.value = Math.max(360, Math.min(maxWidth, nextWidth))
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

function toggleGraphPanel() {
  graphCollapsed.value = !graphCollapsed.value
}

function toggleSettingsView() {
  if (activeView.value === 'settings') {
    settingsPageRef.value?.requestBack()
    return
  }
  activeView.value = 'settings'
}

async function closeMemoryOverlay() {
  const nodeId = String(selectedNodeId.value || '').trim()
  agentBoard.openGraphPanel()
  if (!nodeId) return
  await nextTick()
  await agentBoard.focusNodeInViewport(nodeId)
}

async function refreshProviders() {
  providers.value = await listProviders()
}

async function openWorkAlertTarget(request: { graphId: string; nodeId: string; nonce: number }) {
  const graphId = String(request.graphId || '').trim()
  const nodeId = String(request.nodeId || '').trim()
  if (!graphId || !nodeId) return
  const navigationVersion = ++graphNavigationVersion
  activeView.value = 'board'
  lastError.value = null
  const targetGraph = await loadGraph(graphId)
  if (navigationVersion !== graphNavigationVersion) return

  const resolvedId = String(targetGraph.id || graphId).trim() || graphId
  currentGraphId.value = resolvedId
  currentGraphName.value = String(targetGraph.name || resolvedId)
  currentGraphWorkingPath.value = String((targetGraph as { working_path?: unknown }).working_path || '').trim()
  graphLoadRequest.value = targetGraph
  graphNodeFocusRequest.value = { graphId: resolvedId, nodeId, nonce: request.nonce }
  workspaceReady.value = true
  await setStartupGraphConfig(resolvedId, currentGraphName.value || resolvedId).catch(() => null)
}

function consumeWorkAlertNavigation(request: { graphId: string; nodeId: string; nonce: number }) {
  void openWorkAlertTarget(request)
    .catch((error: unknown) => {
      lastError.value = String((error as { message?: unknown })?.message || error)
    })
    .finally(() => completeWorkAlertNavigation(request.nonce))
}

onMounted(async () => {
  workspaceMounted.value = true
  selectedNodeId.value = null
  memoryMode.value = 'graph'

  leftSidebarWidth.value = readStoredNumber(LEFT_WIDTH_KEY, 280, 160, 600)
  memoryPanelWidth.value = readStoredNumber(
    RIGHT_MEMORY_WIDTH_KEY,
    readStoredNumber(LEGACY_RIGHT_WIDTH_KEY, 560, 360, 980),
    360,
    980,
  )
  graphPanelWidth.value = readStoredNumber(RIGHT_GRAPH_WIDTH_KEY, 560, 360, 980)
  leftCollapsed.value = readStoredBoolean(LEFT_COLLAPSED_KEY, true)
  graphCollapsed.value = readStoredBoolean(GRAPH_COLLAPSED_KEY, false)

  window.addEventListener('mousemove', handleMemoryResize)
  window.addEventListener('mousemove', handleLeftResize)
  window.addEventListener('mouseup', stopMemoryResize)
  window.addEventListener('mouseup', stopLeftResize)
  window.addEventListener('keydown', onWorkspaceKeyDown)

  if (navigationRequest.value) consumeWorkAlertNavigation(navigationRequest.value)

  isLocalClient.value = props.bootstrap.remote_status.is_local_client === true
  providers.value = props.bootstrap.providers
  availableTools.value = props.bootstrap.tools
  if (graphNavigationVersion !== 0) return
  const startupNavigationVersion = graphNavigationVersion
  try {
    const targetGraph = props.bootstrap.startup_graph
    if (startupNavigationVersion !== graphNavigationVersion) return

    const resolvedId = String(targetGraph?.id || 'default')
    currentGraphId.value = resolvedId
    currentGraphName.value = String(targetGraph?.name || resolvedId)
    currentGraphWorkingPath.value = String((targetGraph as any)?.working_path || '').trim()
    graphLoadRequest.value = targetGraph
    workspaceReady.value = true
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
})

watch(
  navigationRequest,
  (request) => {
    if (!request || !workspaceMounted.value) return
    consumeWorkAlertNavigation(request)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  workspaceMounted.value = false
  window.removeEventListener('mousemove', handleMemoryResize)
  window.removeEventListener('mousemove', handleLeftResize)
  window.removeEventListener('mouseup', stopMemoryResize)
  window.removeEventListener('mouseup', stopLeftResize)
  window.removeEventListener('keydown', onWorkspaceKeyDown)
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
    window.localStorage.setItem(RIGHT_MEMORY_WIDTH_KEY, String(value))
  } catch {
    // ignore local storage errors
  }
})

watch(graphPanelWidth, (value) => {
  try {
    window.localStorage.setItem(RIGHT_GRAPH_WIDTH_KEY, String(value))
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

watch(graphCollapsed, (value) => {
  try {
    window.localStorage.setItem(GRAPH_COLLAPSED_KEY, value ? '1' : '0')
  } catch {
    // ignore local storage errors
  }
})

watch(memoryMode, (mode) => {
  if (mode === 'agent') {
    memoryOverlayOpen.value = true
  } else if (mode === 'graph') {
    memoryOverlayOpen.value = false
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
      :active-view="activeView"
      :left-collapsed="leftCollapsed"
      :graph-collapsed="graphCollapsed"
      :can-access-local-files="canAccessLocalFiles"
      :can-open-settings="isDeveloper"
      :initial-remotes="props.bootstrap.remotes"
      @toggle-left="toggleLeftSidebar"
      @toggle-graph="toggleGraphPanel"
      @toggle-settings="toggleSettingsView"
      @error="lastError = $event || null"
    />

    <SettingsPage
      v-if="activeView === 'settings'"
      ref="settingsPageRef"
      :show-back-button="false"
      @back="activeView = 'board'"
      @providers-updated="refreshProviders"
      @defaults-updated="applyDefaultSettings"
    />

    <div v-else class="content" :style="{ '--right-panel-width': `${boardRightWidth}px` }">
      <aside v-if="canAccessLocalFiles" class="left-sidebar" :class="{ collapsed: leftCollapsed }" :style="{ width: `${leftWidth}px` }">
        <FileExplorer v-if="!leftCollapsed" :root-path="fileExplorerRootPath" @file-selected="onFileSelected" />
        <div v-else class="collapsed-mark">{{ t('common.files') }}</div>
      </aside>
      <div v-if="canAccessLocalFiles" class="sidebar-resizer" @mousedown="startLeftResize"></div>

      <div class="center">
        <main class="agent-stage">
          <NodeConfigDock v-if="isDeveloper" />
          <AgentBoard v-if="workspaceReady" />
          <AppErrorToast
            :message="lastError"
            placement="desktop"
            @dismiss="lastError = null"
          />
        </main>
      </div>

      <div
        v-if="!isMemoryFloating"
        class="memory-resizer"
        data-board-occlusion="right"
        @mousedown="startMemoryResize"
      ></div>
      <ConversationWindow
        class="right" :floating="isMemoryFloating" :label="t('common.memory')"
        :data-board-occlusion="isMemoryFloating ? undefined : 'right'"
        :class="{ collapsed: graphCollapsed && !isMemoryFloating, floating: isMemoryFloating }"
        :style="rightPanelStyle" :data-memory-overlay="isMemoryFloating ? 'true' : undefined"
        @close="closeMemoryOverlay"
      >
        <template v-if="isMemoryFloating || !graphCollapsed">
          <div class="memory-panel-content">
            <MemoryPanel
              :initial-graphs="props.bootstrap.graphs"
              :initial-graph-profiles="props.bootstrap.graph_profiles"
              :closable="isMemoryFloating"
              @close="closeMemoryOverlay"
            />
          </div>
          <NodeInputDock v-show="isMemoryFloating" />
        </template>
        <div v-else class="collapsed-mark">{{ t('common.memory') }}</div>
      </ConversationWindow>
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

.content {
  position: relative;
}

/* 左侧文件浏览器 */
.left-sidebar {
  width: 280px;
  display: flex;
  flex-direction: column;
  background-color: var(--theme-panel-file-panel-background-color, var(--bg-primary));
  background-image: var(--theme-panel-file-panel-background-image, none);
  background-size: var(--theme-panel-file-panel-background-size, cover);
  background-position: var(--theme-panel-file-panel-background-position, center);
  background-repeat: var(--theme-panel-file-panel-background-repeat, no-repeat);
  background-blend-mode: var(--theme-panel-file-panel-background-blend-mode, normal);
  border-right: 1px solid var(--theme-panel-file-panel-border-color, var(--border-subtle));
  overflow: hidden;
}

.left-sidebar.collapsed {
  align-items: center;
  justify-content: center;
}

.collapsed-mark {
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  letter-spacing: 2px;
  font-size: 11px;
  font-weight: 500;
  color: var(--theme-panel-memory-panel-text-muted, var(--text-tertiary));
  text-transform: uppercase;
  user-select: none;
}

/* 调整分隔条 - 视觉细但拖拽区域大 */
.sidebar-resizer {
  width: 3px;
  cursor: col-resize;
  background: var(--theme-panel-app-border-subtle, var(--border-subtle));
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
  background: var(--theme-panel-app-text-accent, var(--accent-blue));
}

.memory-resizer {
  width: 3px;
  position: absolute;
  top: 0;
  right: var(--right-panel-width);
  bottom: 0;
  cursor: col-resize;
  background: var(--theme-panel-app-border-subtle, var(--border-subtle));
  transition: background 0.15s ease;
  flex-shrink: 0;
  z-index: 120;
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
  background: var(--theme-panel-app-text-accent, var(--accent-blue));
}

.memory-panel-content {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

</style>
