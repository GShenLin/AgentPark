<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  clearNodeInstanceMemory,
  createGraphFromProfile,
  deleteGraph,
  deleteGraphProfile,
  deleteNodeInstanceMemoryMessage,
  listGraphProfiles,
  listGraphs,
  listNodeInstanceConfigs,
  loadGraph,
  saveGraph,
  saveGraphProfileFromGraph,
  setStartupGraphConfig,
  type GraphConfig,
  type GraphInfo,
  type GraphProfile,
  type MessageEnvelope,
  type NodeInstanceConfig,
} from '../api'
import { useGlobalState } from '../composables/useGlobalState'
import { useMemory } from '../composables/useMemory'
import { useMemoryMessageExport } from '../composables/useMemoryMessageExport'
import MemoryContentView from './MemoryContentView.vue'
import MemoryPanelHeader from './MemoryPanelHeader.vue'
import MemorySaveDialog from './MemorySaveDialog.vue'
import { renderMemoryMarkdown } from './memoryMarkdown'

const {
  memoryText,
  memoryMessages,
  memoryHistoryComplete,
  memoryLatestTurnProgressLoaded,
  memoryLatestTurnMetadataLoaded,
  memoryLiveMessage,
  memoryThinkingMessage,
  memoryActivityMessage,
  memoryInteractiveSessionId,
  memoryInteractiveSending,
  memoryTitle,
  memoryMeta,
  memoryMode,
  memoryRefreshRequest,
  memoryLiveRefreshRequest,
  agentImages,
  selectedNodeId,
  graphSnapshot,
  graphLoadRequest,
  graphNodeFocusRequest,
  currentGraphId,
  currentGraphName,
  currentGraphWorkingPath,
  lastError,
} = useGlobalState()

const {
  isSaving,
  memoryAutoScroll,
  loadAgentMemory,
  loadAgentLiveMessage,
  startAgentLiveStream,
  saveCurrentFile,
  stopLoading,
  sendInteractiveInput,
} = useMemory()

const {
  saveDialogOpen,
  saveDialogFilename,
  saveDialogTargetDir,
  saveDialogError,
  saveDialogSaving,
  openSaveMessageDialog,
  confirmSaveMessageDialog,
  cancelSaveMessageDialog,
  copyMessageText,
} = useMemoryMessageExport()

const isWordWrap = ref(true)
const showLineNumbers = ref(false)
const isMarkdownPreview = ref(true)
const contentViewRef = ref<InstanceType<typeof MemoryContentView> | null>(null)
const interactiveInputText = ref('')
const lazySectionLoading = ref<'progress' | 'metadata' | null>(null)

const graphs = ref<GraphInfo[]>([])
const graphProfiles = ref<GraphProfile[]>([])
const selectedGraphProfileId = ref('')
const graphNameInput = ref('')
const graphWorkingPathInput = ref('')
const graphStatus = ref<string | null>(null)
const graphLoading = ref(false)
const graphMemoryClearingId = ref('')
const expandedGraphId = ref('')
const graphNodesLoadingId = ref('')
const graphNodesById = ref<Record<string, NodeInstanceConfig[]>>({})

const structuredMessages = computed(() => (Array.isArray(memoryMessages.value) ? memoryMessages.value : []))
const canClearMemory = computed(() => memoryMode.value === 'agent' && hasSelectedNodeTarget())
const canSendInteractiveInput = computed(
  () => !!String(selectedNodeId.value || '').trim() && !!String(memoryInteractiveSessionId.value || '').trim() && !memoryInteractiveSending.value,
)

function hasSelectedNodeTarget() {
  return !!String(selectedNodeId.value || '').trim()
}

function defaultMemoryMode() {
  return hasSelectedNodeTarget() ? 'agent' : 'graph'
}

function toggleFileMode() {
  memoryMode.value = memoryMode.value === 'file' ? defaultMemoryMode() : 'file'
}

async function clearSelectedNodeMemory() {
  const nodeId = String(selectedNodeId.value || '').trim()
  if (!nodeId) return
  const ok = window.confirm(`Clear all memory for node "${nodeId}"?`)
  if (!ok) return
  try {
    await clearNodeInstanceMemory(nodeId, currentGraphId.value || 'default')
    if (String(selectedNodeId.value || '').trim() === nodeId) {
      memoryText.value = ''
      memoryMessages.value = []
      memoryLiveMessage.value = ''
      memoryThinkingMessage.value = ''
      memoryActivityMessage.value = ''
      await loadAgentMemory()
    }
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
}

function graphNodeIdsFromConfigs(result: Awaited<ReturnType<typeof listNodeInstanceConfigs>>) {
  const ids = Array.isArray(result.node_ids)
    ? result.node_ids
    : (Array.isArray(result.nodes) ? result.nodes.map((node) => node.node_id) : [])
  return Array.from(new Set(ids.map((id) => String(id || '').trim()).filter(Boolean)))
}

async function handleSendInteractiveInput(options: { appendNewline?: boolean; sendEof?: boolean; sendCtrlC?: boolean } = {}) {
  const text = interactiveInputText.value
  const ok = await sendInteractiveInput(text, options)
  if (ok) {
    interactiveInputText.value = ''
  }
}

async function onInteractiveSubmit() {
  if (!canSendInteractiveInput.value) return
  await handleSendInteractiveInput({ appendNewline: true })
}

async function onInteractiveCtrlC() {
  if (!canSendInteractiveInput.value) return
  await handleSendInteractiveInput({ appendNewline: false, sendCtrlC: true })
}

async function onInteractiveEof() {
  if (!canSendInteractiveInput.value) return
  await handleSendInteractiveInput({ appendNewline: false, sendEof: true })
}

async function deleteMemoryMessage(target: MessageEnvelope | MessageEnvelope[]) {
  const nodeId = String(selectedNodeId.value || '').trim()
  const messages = Array.isArray(target) ? target : [target]
  const messageIds = Array.from(new Set(
    messages
      .map((message) => String((message as any)?.id || '').trim())
      .filter(Boolean),
  ))
  if (!nodeId || messageIds.length === 0) return
  const label = messageIds.length === 1
    ? 'this conversation entry'
    : `these ${messageIds.length} conversation entries`
  const ok = window.confirm(`Delete ${label}?`)
  if (!ok) return
  try {
    for (const messageId of messageIds) {
      await deleteNodeInstanceMemoryMessage(nodeId, messageId, currentGraphId.value || 'default')
    }
    const deletedIds = new Set(messageIds)
    memoryMessages.value = memoryMessages.value.filter(
      (item) => !deletedIds.has(String((item as any)?.id || '').trim()),
    )
    await loadAgentMemory()
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
}

const renderedMarkdown = computed(() => {
  return renderMemoryMarkdown(memoryText.value)
})

async function loadPreviousTurns() {
  if (memoryHistoryComplete.value) return
  await loadAgentMemory({ historyMode: 'all' })
}

async function loadLatestTurnSection(section: 'progress' | 'metadata') {
  if (lazySectionLoading.value) return
  if (section === 'progress' && memoryLatestTurnProgressLoaded.value) return
  if (section === 'metadata' && memoryLatestTurnMetadataLoaded.value) return
  lazySectionLoading.value = section
  try {
    await loadAgentMemory({
      historyMode: section === 'progress' ? 'latest_turn_progress' : 'latest_turn_metadata',
    })
  } finally {
    lazySectionLoading.value = null
  }
}

async function refreshGraphs() {
  graphLoading.value = true
  graphStatus.value = null
  try {
    graphs.value = await listGraphs()
    graphProfiles.value = await listGraphProfiles()
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  } finally {
    graphLoading.value = false
  }
}

async function toggleGraphNodes(item: GraphInfo) {
  const graphId = String(item.id || '').trim()
  if (!graphId) return
  if (expandedGraphId.value === graphId) {
    expandedGraphId.value = ''
    return
  }

  expandedGraphId.value = graphId
  if (graphNodesById.value[graphId]) return

  graphNodesLoadingId.value = graphId
  graphStatus.value = null
  try {
    const result = await listNodeInstanceConfigs(graphId)
    graphNodesById.value = {
      ...graphNodesById.value,
      [graphId]: Array.isArray(result.nodes) ? result.nodes : [],
    }
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  } finally {
    if (graphNodesLoadingId.value === graphId) {
      graphNodesLoadingId.value = ''
    }
  }
}

function promptProfileId(defaultValue: string) {
  return String(window.prompt('Profile ID', defaultValue) || '').trim()
}

function promptProfileName(defaultValue: string) {
  return String(window.prompt('Profile name', defaultValue) || '').trim()
}

function resolveGraphName(snapshot: GraphConfig | null) {
  const raw = graphNameInput.value.trim() || currentGraphName.value || snapshot?.name || ''
  if (raw) return raw
  return `graph-${Date.now()}`
}

function updateGraphWorkingPath(value: string) {
  const path = String(value || '').trim()
  graphWorkingPathInput.value = path
  currentGraphWorkingPath.value = path
}

async function saveGraphConfig() {
  const snapshot = graphSnapshot.value
  if (!snapshot) {
    graphStatus.value = 'No graph snapshot to save.'
    return
  }

  graphStatus.value = null
  const name = resolveGraphName(snapshot)
  const sourceGraphId = String(currentGraphId.value || snapshot.id || '').trim()
  const payload: GraphConfig = {
    ...snapshot,
    id: currentGraphId.value || snapshot.id || name,
    name,
    working_path: graphWorkingPathInput.value.trim(),
  }

  try {
    const result = await saveGraph(name, payload, {
      saveReason: 'memory_panel_save',
      sourceGraphId: sourceGraphId && sourceGraphId !== name ? sourceGraphId : undefined,
    })
    const savedAsNewGraph = !!sourceGraphId && sourceGraphId !== result.id
    currentGraphId.value = result.id
    currentGraphName.value = result.name
    currentGraphWorkingPath.value = payload.working_path || ''
    graphNameInput.value = result.name
    if (savedAsNewGraph) {
      graphLoadRequest.value = await loadGraph(result.id)
    }
    await setStartupGraphConfig(result.id, result.name).catch(() => null)
    await refreshGraphs()
    graphStatus.value = 'Graph saved.'
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function saveGraphProfile() {
  const graphId = String(currentGraphId.value || graphSnapshot.value?.id || 'default').trim() || 'default'
  const defaultName = String(currentGraphName.value || graphNameInput.value || graphId).trim() || graphId
  const defaultProfileId = defaultName.replace(/[^A-Za-z0-9_-]/g, '_') || graphId
  const profileId = promptProfileId(defaultProfileId)
  if (!profileId) return
  const profileName = promptProfileName(defaultName) || profileId

  graphStatus.value = null
  try {
    if (graphSnapshot.value) {
      await saveGraph(graphId, {
        ...graphSnapshot.value,
        id: graphId,
        name: currentGraphName.value || graphNameInput.value || graphId,
        working_path: graphWorkingPathInput.value.trim(),
      }, { saveReason: 'graph_profile_save' })
    }
    const result = await saveGraphProfileFromGraph({
      graph_id: graphId,
      profile_id: profileId,
      profile_name: profileName,
    })
    selectedGraphProfileId.value = result.profile.id
    graphProfiles.value = await listGraphProfiles()
    graphStatus.value = 'Graph profile saved.'
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function createGraphConfigFromProfile() {
  const profileId = String(selectedGraphProfileId.value || '').trim()
  if (!profileId) {
    graphStatus.value = 'Select a graph profile first.'
    return
  }
  const targetGraphId = String(window.prompt('GraphID', '') || '').trim()
  if (!targetGraphId) return

  graphStatus.value = null
  try {
    const result = await createGraphFromProfile(profileId, targetGraphId)
    const graph = result.graph
    currentGraphId.value = graph.id
    currentGraphName.value = graph.name || graph.id
    currentGraphWorkingPath.value = String((graph as any)?.working_path || '').trim()
    graphNameInput.value = currentGraphName.value || graph.id
    graphWorkingPathInput.value = currentGraphWorkingPath.value
    graphLoadRequest.value = graph
    memoryMode.value = 'graph'
    await setStartupGraphConfig(graph.id, graph.name || graph.id).catch(() => null)
    await refreshGraphs()
    graphStatus.value = 'Graph created from profile.'
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function deleteSelectedGraphProfile() {
  const profileId = String(selectedGraphProfileId.value || '').trim()
  if (!profileId) {
    graphStatus.value = 'Select a graph profile first.'
    return
  }
  const profile = graphProfiles.value.find((item) => item.id === profileId)
  const profileName = String(profile?.name || profileId)
  const ok = window.confirm(`Delete profile "${profileName}"? This cannot be undone.`)
  if (!ok) return

  graphStatus.value = null
  try {
    await deleteGraphProfile(profileId)
    selectedGraphProfileId.value = ''
    graphProfiles.value = await listGraphProfiles()
    graphStatus.value = 'Graph profile deleted.'
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function loadGraphConfig(item: GraphInfo, focusNodeId = '') {
  const requestedFocusNodeId = String(focusNodeId || '').trim()
  graphStatus.value = null
  try {
    const current = graphSnapshot.value
    const ifVersion = current?.id === item.id ? Number((current as any)?.version || 0) : 0
    const res = await loadGraph(item.id, { ifVersion })
    if (res.unchanged) {
      currentGraphId.value = item.id
      currentGraphName.value = item.name || item.id
      graphNameInput.value = item.name || item.id
      await setStartupGraphConfig(item.id, item.name || item.id).catch(() => null)
      if (requestedFocusNodeId) {
        graphNodeFocusRequest.value = { graphId: item.id, nodeId: requestedFocusNodeId, nonce: Date.now() }
      }
      memoryMode.value = 'graph'
      return
    }
    currentGraphId.value = res.id
    currentGraphName.value = res.name
    currentGraphWorkingPath.value = String((res as any)?.working_path || '').trim()
    graphNameInput.value = res.name
    graphWorkingPathInput.value = currentGraphWorkingPath.value
    graphLoadRequest.value = res
    await setStartupGraphConfig(res.id, res.name).catch(() => null)
    if (requestedFocusNodeId) {
      graphNodeFocusRequest.value = { graphId: res.id, nodeId: requestedFocusNodeId, nonce: Date.now() }
    }
    memoryMode.value = 'graph'
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function navigateToGraphNode(payload: { graph: GraphInfo; nodeId: string }) {
  const nodeId = String(payload.nodeId || '').trim()
  if (!nodeId) return
  await loadGraphConfig(payload.graph, nodeId)
}

async function deleteGraphConfig(item: GraphInfo) {
  const name = item.name || item.id
  const ok = window.confirm(`Delete graph "${name}"? This will remove the whole graph folder and cannot be undone.`)
  if (!ok) return

  graphStatus.value = null
  try {
    await deleteGraph(item.id)
    if (currentGraphId.value === item.id) {
      currentGraphId.value = 'default'
      currentGraphName.value = 'default'
      currentGraphWorkingPath.value = ''
      graphNameInput.value = 'default'
      graphWorkingPathInput.value = ''
      graphLoadRequest.value = { id: 'default', name: 'default', nodes: [], output_routes: {} }
      await setStartupGraphConfig('default', 'default').catch(() => null)
    }
    await refreshGraphs()
    graphStatus.value = `Graph deleted: ${name}`
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function clearGraphMemory(item: GraphInfo) {
  const graphId = String(item.id || '').trim()
  if (!graphId) return
  const name = item.name || graphId
  const ok = window.confirm(`Clear all memory for every node in graph "${name}"?`)
  if (!ok) return

  graphStatus.value = null
  graphMemoryClearingId.value = graphId
  try {
    const configs = await listNodeInstanceConfigs(graphId)
    const nodeIds = graphNodeIdsFromConfigs(configs)
    let clearedFiles = 0
    for (const nodeId of nodeIds) {
      const result = await clearNodeInstanceMemory(nodeId, graphId)
      clearedFiles += Number(result.cleared_files || 0)
    }

    const selectedNode = String(selectedNodeId.value || '').trim()
    if (memoryMode.value === 'agent' && (currentGraphId.value || 'default') === graphId && nodeIds.includes(selectedNode)) {
      memoryText.value = ''
      memoryMessages.value = []
      memoryLiveMessage.value = ''
      memoryThinkingMessage.value = ''
      memoryActivityMessage.value = ''
      await loadAgentMemory()
    }
    graphStatus.value = `Graph memory cleared: ${name} (${nodeIds.length} nodes, ${clearedFiles} files).`
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  } finally {
    graphMemoryClearingId.value = ''
  }
}

watch(
  () => selectedNodeId.value,
  async () => {
    if (memoryMode.value !== 'agent') return
    stopLoading()
    memoryAutoScroll.value = true
    await loadAgentMemory({ historyMode: 'latest_turn' })
    startAgentLiveStream()
  },
)

watch(
  () => memoryMode.value,
  async (mode) => {
    stopLoading()

    if (mode === 'agent') {
      memoryAutoScroll.value = true
      await loadAgentMemory({ historyMode: 'latest_turn' })
      startAgentLiveStream()
      return
    }

    if (mode === 'graph') {
      memoryTitle.value = currentGraphName.value || 'Graph'
      graphWorkingPathInput.value = currentGraphWorkingPath.value
      await refreshGraphs()
    }
  },
  { immediate: true },
)

watch(
  () => memoryRefreshRequest.value,
  async () => {
    if (memoryMode.value !== 'agent') return
    if (!hasSelectedNodeTarget()) return
    await loadAgentMemory()
    startAgentLiveStream()
  },
)

watch(
  () => memoryLiveRefreshRequest.value,
  async () => {
    if (memoryMode.value !== 'agent') return
    if (!hasSelectedNodeTarget()) return
    await loadAgentLiveMessage()
  },
)

watch(
  () => currentGraphName.value,
  (name) => {
    if (!graphNameInput.value && name) {
      graphNameInput.value = name
    }
  },
)

watch(
  () => currentGraphWorkingPath.value,
  (path) => {
    graphWorkingPathInput.value = String(path || '').trim()
  },
  { immediate: true },
)

watch(memoryText, async () => {
  if (!memoryAutoScroll.value) return
  if (memoryMode.value !== 'agent') return
  await nextTick()
  contentViewRef.value?.scrollToBottom()
})

watch(memoryMessages, async () => {
  if (!memoryAutoScroll.value) return
  if (memoryMode.value !== 'agent') return
  await nextTick()
  contentViewRef.value?.scrollToBottom()
})

watch(memoryLiveMessage, async () => {
  if (!memoryAutoScroll.value) return
  if (memoryMode.value !== 'agent') return
  await nextTick()
  contentViewRef.value?.scrollToBottom()
})

watch(
  () => memoryInteractiveSessionId.value,
  async (sessionId) => {
    if (!sessionId) return
    if (!memoryAutoScroll.value) return
    if (memoryMode.value !== 'agent') return
    await nextTick()
    contentViewRef.value?.scrollToBottom()
    contentViewRef.value?.focusInteractiveInput?.()
  },
)

onBeforeUnmount(() => {
  stopLoading()
})
</script>

<template>
  <div class="panel">
    <MemoryPanelHeader
      :memory-mode="memoryMode"
      v-model:is-markdown-preview="isMarkdownPreview"
      v-model:show-line-numbers="showLineNumbers"
      v-model:is-word-wrap="isWordWrap"
      :memory-title="memoryTitle"
      :memory-meta="memoryMeta"
      :is-saving="isSaving"
      :graph-status="graphStatus"
      :can-clear-memory="canClearMemory"
      @clear-memory="clearSelectedNodeMemory"
      @toggle-file-mode="toggleFileMode"
    />

    <MemoryContentView
      ref="contentViewRef"
      v-model:memory-text="memoryText"
      v-model:graph-name-input="graphNameInput"
      :graph-working-path-input="graphWorkingPathInput"
      :mode="memoryMode"
      :messages="structuredMessages"
      :history-complete="memoryHistoryComplete"
      :progress-loaded="memoryLatestTurnProgressLoaded"
      :metadata-loaded="memoryLatestTurnMetadataLoaded"
      :loading-section="lazySectionLoading"
      :live-message="memoryLiveMessage"
      :thinking-message="memoryThinkingMessage"
      :activity-message="memoryActivityMessage"
      :markdown-preview="isMarkdownPreview"
      :word-wrap="isWordWrap"
      :show-line-numbers="showLineNumbers"
      :agent-images="agentImages"
      :rendered-markdown="renderedMarkdown"
      :graph-loading="graphLoading"
      :graph-memory-clearing-id="graphMemoryClearingId"
      :graph-nodes-loading-id="graphNodesLoadingId"
      :expanded-graph-id="expandedGraphId"
      :graphs="graphs"
      :graph-nodes-by-id="graphNodesById"
      :graph-profiles="graphProfiles"
      :selected-graph-profile-id="selectedGraphProfileId"
      :interactive-session-id="memoryInteractiveSessionId"
      :interactive-input-disabled="!canSendInteractiveInput"
      :interactive-sending="memoryInteractiveSending"
      :interactive-input-text="interactiveInputText"
      @save-current-file="saveCurrentFile"
      @save-graph-config="saveGraphConfig"
      @save-graph-profile="saveGraphProfile"
      @create-graph-from-profile="createGraphConfigFromProfile"
      @delete-graph-profile="deleteSelectedGraphProfile"
      @refresh-graphs="refreshGraphs"
      @toggle-graph-nodes="toggleGraphNodes"
      @load-graph-config="loadGraphConfig"
      @navigate-graph-node="navigateToGraphNode"
      @clear-graph-memory="clearGraphMemory"
      @delete-graph-config="deleteGraphConfig"
      @graph-path-error="graphStatus = $event"
      @update:selected-graph-profile-id="selectedGraphProfileId = $event"
      @update:graph-working-path-input="updateGraphWorkingPath"
      @auto-scroll-change="memoryAutoScroll = $event"
      @save-message="openSaveMessageDialog"
      @copy-message="copyMessageText"
      @delete-message="deleteMemoryMessage"
      @request-history="loadPreviousTurns"
      @request-section="loadLatestTurnSection"
      @update:interactive-input-text="interactiveInputText = $event"
      @send-interactive-input="handleSendInteractiveInput($event)"
      @interactive-submit="onInteractiveSubmit"
      @interactive-ctrl-c="onInteractiveCtrlC"
      @interactive-eof="onInteractiveEof"
    />

    <MemorySaveDialog
      v-model:filename="saveDialogFilename"
      :open="saveDialogOpen"
      :target-dir="saveDialogTargetDir"
      :error="saveDialogError"
      :saving="saveDialogSaving"
      @confirm="confirmSaveMessageDialog"
      @cancel="cancelSaveMessageDialog"
    />
  </div>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background-color: var(--theme-panel-memory-panel-background-color, rgba(2, 6, 23, 0.56));
  background-image: var(--theme-panel-memory-panel-background-image, none);
  background-size: var(--theme-panel-memory-panel-background-size, cover);
  background-position: var(--theme-panel-memory-panel-background-position, center);
  background-repeat: var(--theme-panel-memory-panel-background-repeat, no-repeat);
  background-blend-mode: var(--theme-panel-memory-panel-background-blend-mode, normal);
  border: 1px solid var(--theme-panel-memory-panel-border-color, rgba(148, 163, 184, 0.15));
  border-radius: 14px;
}

:deep(.markdown-body) {
  padding: 16px;
  overflow-y: auto;
  line-height: 1.6;
  font-size: 13px;
  white-space: normal !important;
  word-wrap: break-word;
}

:deep(.markdown-body .mem-log) {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

:deep(.markdown-body .mem-msg) {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.22);
  overflow: hidden;
}

:deep(.markdown-body .mem-msg-user) {
  border-left: 4px solid rgba(56, 189, 248, 0.6);
}

:deep(.markdown-body .mem-msg-assistant) {
  border-left: 4px solid rgba(34, 197, 94, 0.55);
}

:deep(.markdown-body .mem-msg-system) {
  border-left: 4px solid rgba(148, 163, 184, 0.5);
}

:deep(.markdown-body .mem-msg-commentary) {
  border-left: 4px solid rgba(250, 204, 21, 0.62);
}

:deep(.markdown-body .mem-msg-tool) {
  border-left: 4px solid rgba(244, 114, 182, 0.62);
}

:deep(.markdown-body .mem-msg-head) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: rgba(0, 0, 0, 0.18);
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  font-size: 12px;
}

:deep(.markdown-body .mem-role) {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
}

:deep(.markdown-body .mem-role-user) {
  background: rgba(56, 189, 248, 0.14);
  color: rgba(125, 211, 252, 0.95);
}

:deep(.markdown-body .mem-role-assistant) {
  background: rgba(34, 197, 94, 0.16);
  color: rgba(187, 247, 208, 0.95);
}

:deep(.markdown-body .mem-role-system) {
  background: rgba(148, 163, 184, 0.14);
  color: rgba(203, 213, 225, 0.95);
}

:deep(.markdown-body .mem-role-commentary) {
  background: rgba(250, 204, 21, 0.14);
  color: rgba(254, 240, 138, 0.98);
}

:deep(.markdown-body .mem-role-tool) {
  background: rgba(244, 114, 182, 0.14);
  color: rgba(251, 207, 232, 0.98);
}

:deep(.markdown-body .mem-msg-body) {
  padding: 10px 12px;
}

:deep(.markdown-body pre) {
  background: rgba(0, 0, 0, 0.3);
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
}

:deep(.markdown-body .markdown-code-block pre) {
  margin: 0;
  padding: 10px 48px 34px 10px;
  background: transparent;
}

</style>
