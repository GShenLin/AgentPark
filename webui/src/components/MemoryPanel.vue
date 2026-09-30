<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  getNodeInstanceMemory,
  clearNodeInstanceMemory,
  createGraphFromProfile,
  deleteGraph,
  deleteGraphProfile,
  deleteNodeInstanceMemoryMessage,
  deleteNodeInstanceMemoryMessages,
  deleteNodeInstanceMemoryTurn,
  listGraphProfiles,
  listGraphs,
  listNodeInstanceConfigs,
  loadGraph,
  moveNodeInstance,
  saveGraph,
  saveGraphProfileFromGraph,
  setGraphVisibility,
  setStartupGraphConfig,
  type GraphConfig,
  type GraphInfo,
  type GraphProfile,
  type MessageEnvelope,
} from '../api'
import { useGlobalState } from '../composables/useGlobalState'
import { useMemory } from '../composables/useMemory'
import { useMemoryMessageExport } from '../composables/useMemoryMessageExport'
import { useCliSessions } from '../composables/useCliSessions'
import { recordDeletionUndo } from '../composables/useDeletionUndo'
import MemoryContentView from './MemoryContentView.vue'
import MemoryPanelHeader from './MemoryPanelHeader.vue'
import MemorySaveDialog from './MemorySaveDialog.vue'
import CliSessionPicker from './CliSessionPicker.vue'
import { renderMemoryMarkdown } from './memoryMarkdown'
import { t } from '../i18n'
import { AgentBoardKey } from './agent-board/context'

const board = inject(AgentBoardKey, null)

const props = defineProps<{
  initialGraphs: GraphInfo[]
  initialGraphProfiles: GraphProfile[]
  closable?: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const {
  memoryText,
  memoryMessages,
  memoryLiveMessage,
  memoryThinkingMessage,
  memoryActivityMessage,
  memoryActivityBlocks,
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
  nodeGraphMoveRequest,
  nodeGraphMoveInProgress,
} = useGlobalState()

let autoScrollFrame: number | null = null

function scheduleAutoScroll(focusInteractive = false) {
  if (!memoryAutoScroll.value || memoryMode.value !== 'agent') return
  if (autoScrollFrame != null) return
  autoScrollFrame = window.requestAnimationFrame(async () => {
    autoScrollFrame = null
    if (!memoryAutoScroll.value || memoryMode.value !== 'agent') return
    await nextTick()
    contentViewRef.value?.scrollToBottom()
    if (focusInteractive) contentViewRef.value?.focusInteractiveInput?.()
  })
}

const {
  isSaving,
  memoryAutoScroll,
  loadAgentMemory,
  loadAgentLiveMessage,
  beginAgentSelection,
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

const graphs = ref<GraphInfo[]>([...props.initialGraphs])
const graphProfiles = ref<GraphProfile[]>([...props.initialGraphProfiles])
const selectedGraphProfileId = ref('')
const graphNameInput = ref('')
const graphWorkingPathInput = ref('')
const graphStatus = ref<string | null>(null)
const graphLoading = ref(false)
const graphMemoryClearingId = ref('')

function hasSelectedNodeTarget() {
  return !!String(selectedNodeId.value || '').trim()
}

const {
  cliSessionState,
  cliSessionLoading,
  refreshCliSessions,
  chooseCliSession,
  resetCliSessions,
  cliMemoryClearTargetLabel,
} = useCliSessions({
  getNodeId: () => String(selectedNodeId.value || ''),
  getGraphId: () => String(currentGraphId.value || 'default'),
  isEnabled: () => memoryMode.value === 'agent' && hasSelectedNodeTarget(),
  onAfterSelect: async () => {
    memoryText.value = ''
    memoryMessages.value = []
    memoryLiveMessage.value = ''
    memoryThinkingMessage.value = ''
    memoryActivityMessage.value = ''
    memoryActivityBlocks.value = []
    beginAgentSelection()
    await loadAgentMemory()
  },
  onError: (error: any) => {
    lastError.value = String(error?.message || error)
  },
})

const structuredMessages = computed(() => (Array.isArray(memoryMessages.value) ? memoryMessages.value : []))
const canClearMemory = computed(() => memoryMode.value === 'agent' && hasSelectedNodeTarget())
const canSendInteractiveInput = computed(
  () => !!String(selectedNodeId.value || '').trim() && !!String(memoryInteractiveSessionId.value || '').trim() && !memoryInteractiveSending.value,
)

function defaultMemoryMode() {
  return hasSelectedNodeTarget() ? 'agent' : 'graph'
}

function toggleFileMode() {
  memoryMode.value = memoryMode.value === 'file' ? defaultMemoryMode() : 'file'
}

async function clearSelectedNodeMemory() {
  const nodeId = String(selectedNodeId.value || '').trim()
  if (!nodeId) return
  const targetLabel = cliMemoryClearTargetLabel(nodeId)
  const ok = window.confirm(t('mobile.clearTargetConfirm', { target: targetLabel }))
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
      void refreshCliSessions()
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

async function deleteMemoryMessage(target: MessageEnvelope | MessageEnvelope[] | { kind: 'turn'; userMessage: MessageEnvelope }) {
  const nodeId = String(selectedNodeId.value || '').trim()
  const isTurn = !Array.isArray(target) && (target as any)?.kind === 'turn'
  if (isTurn) {
    const userMessageId = String(((target as any).userMessage as any)?.id || '').trim()
    if (!nodeId || !userMessageId) return
    const ok = window.confirm(t('mobile.deleteTurnConfirm'))
    if (!ok) return
    try {
      const result = await deleteNodeInstanceMemoryTurn(nodeId, userMessageId, currentGraphId.value || 'default')
      recordDeletionUndo(result.undo_token ? {
        token: result.undo_token,
        kind: 'delete_dialogue',
        label: t('mobile.conversationTurn'),
      } : null)
      const deletedIds = new Set(result.message_ids)
      memoryMessages.value = memoryMessages.value.filter(
        (item) => !deletedIds.has(String((item as any)?.id || '').trim()),
      )
      await loadAgentMemory()
    } catch (e: any) {
      lastError.value = String(e?.message || e)
    }
    return
  }
  const messages = Array.isArray(target) ? target : [target]
  const messageIds = Array.from(new Set(
    messages
      .map((message) => String((message as any)?.id || '').trim())
      .filter(Boolean),
  ))
  if (!nodeId || messageIds.length === 0) return
  const label = messageIds.length === 1
    ? t('mobile.conversationEntry')
    : t('mobile.conversationEntries', { count: messageIds.length })
  const ok = window.confirm(t('mobile.deleteEntryConfirm', { label }))
  if (!ok) return
  try {
    const result = messageIds.length === 1
      ? await deleteNodeInstanceMemoryMessage(nodeId, messageIds[0]!, currentGraphId.value || 'default')
      : await deleteNodeInstanceMemoryMessages(nodeId, messageIds, currentGraphId.value || 'default')
    recordDeletionUndo(result.undo_token ? {
      token: result.undo_token,
      kind: 'delete_dialogue',
      label: messageIds.length === 1 ? 'conversation entry' : `${messageIds.length} conversation entries`,
    } : null)
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

async function loadTurnDetails(turnId: string): Promise<MessageEnvelope[]> {
  const result = await getNodeInstanceMemory(
    String(selectedNodeId.value || ''), 0, currentGraphId.value || 'default',
    'turn_details', { turnId },
  )
  if (!result.messages) throw new Error('Process response is missing messages')
  return result.messages
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

function promptProfileId(defaultValue: string) {
  return String(window.prompt(t('memory.profileId'), defaultValue) || '').trim()
}

function promptProfileName(defaultValue: string) {
  return String(window.prompt(t('memory.profileName'), defaultValue) || '').trim()
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
    graphStatus.value = t('memory.noGraphSnapshot')
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
    graphStatus.value = t('memory.graphSaved')
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
    graphStatus.value = t('memory.graphProfileSaved')
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function createGraphConfigFromProfile() {
  const profileId = String(selectedGraphProfileId.value || '').trim()
  if (!profileId) {
    graphStatus.value = t('memory.selectProfile')
    return
  }
  const targetGraphId = String(window.prompt(t('mobile.graphId'), '') || '').trim()
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
    graphStatus.value = t('memory.createdFromProfile')
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function deleteSelectedGraphProfile() {
  const profileId = String(selectedGraphProfileId.value || '').trim()
  if (!profileId) {
    graphStatus.value = t('memory.selectProfile')
    return
  }
  const profile = graphProfiles.value.find((item) => item.id === profileId)
  const profileName = String(profile?.name || profileId)
  const ok = window.confirm(t('memory.deleteProfileConfirm', { name: profileName }))
  if (!ok) return

  graphStatus.value = null
  try {
    await deleteGraphProfile(profileId)
    selectedGraphProfileId.value = ''
    graphProfiles.value = await listGraphProfiles()
    graphStatus.value = t('memory.profileDeleted')
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
      return true
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
    return true
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
    return false
  }
}

async function navigateToGraphNode(payload: { graph: GraphInfo; nodeId: string }) {
  const nodeId = String(payload.nodeId || '').trim()
  if (!nodeId) return
  await loadGraphConfig(payload.graph, nodeId)
}

async function navigateToGraphGroup(payload: { graph: GraphInfo; groupId: string }) {
  if (!board) return
  if (!await loadGraphConfig(payload.graph)) return
  await nextTick()
  try {
    await board.groups.refresh()
    if (currentGraphId.value !== payload.graph.id) return
    if (!board.groups.groups.value.some(group => group.id === payload.groupId)) {
      throw new Error(t('memory.groupUnavailable'))
    }
    board.groups.activeId.value = payload.groupId
  } catch (cause) {
    graphStatus.value = cause instanceof Error ? cause.message : String(cause)
  }
}

let handledNodeGraphMoveNonce = 0
watch(
  () => nodeGraphMoveRequest.value,
  async (request) => {
    if (!request || request.nonce === handledNodeGraphMoveNonce || nodeGraphMoveInProgress.value) return
    handledNodeGraphMoveNonce = request.nonce
    nodeGraphMoveInProgress.value = true
    graphStatus.value = null
    try {
      await moveNodeInstance(request.nodeId, request.sourceGraphId, request.targetGraphId)
      if ((currentGraphId.value || 'default') === request.sourceGraphId) {
        if (selectedNodeId.value === request.nodeId) selectedNodeId.value = null
        graphLoadRequest.value = await loadGraph(request.sourceGraphId)
      }
      await refreshGraphs()
      graphStatus.value = t('memory.nodeMoved', {
        node: request.nodeId,
        graph: request.targetGraphId,
      })
    } catch (e: any) {
      const message = String(e?.message || e)
      graphStatus.value = message
      lastError.value = message
    } finally {
      nodeGraphMoveInProgress.value = false
      if (nodeGraphMoveRequest.value?.nonce === request.nonce) nodeGraphMoveRequest.value = null
    }
  },
)

async function deleteGraphConfig(item: GraphInfo) {
  const name = item.name || item.id
  const ok = window.confirm(t('memory.deleteGraphUndo', { name }))
  if (!ok) return

  graphStatus.value = null
  try {
    const result = await deleteGraph(item.id)
    recordDeletionUndo(result.undo_token ? {
      token: result.undo_token,
      kind: 'delete_graph',
      label: `graph ${name}`,
    } : null)
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
    graphStatus.value = t('mobile.graphDeleted', { name })
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function toggleGraphVisibility(item: GraphInfo) {
  const graphId = String(item.id || '').trim()
  if (!graphId) return
  const nextPrivate = !item.private
  graphStatus.value = null
  try {
    await setGraphVisibility(graphId, nextPrivate)
    await refreshGraphs()
    graphStatus.value = t('memory.graphVisibility', {
      visibility: nextPrivate ? t('memory.private') : t('memory.public'),
      name: item.name || graphId,
    })
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

async function clearGraphMemory(item: GraphInfo) {
  const graphId = String(item.id || '').trim()
  if (!graphId) return
  const name = item.name || graphId
  const ok = window.confirm(t('memory.clearGraphConfirm', { name }))
  if (!ok) return

  graphStatus.value = null
  graphMemoryClearingId.value = graphId
  try {
    const configs = await listNodeInstanceConfigs(graphId, 0, 'board')
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
    graphStatus.value = t('memory.graphCleared', { name, nodes: nodeIds.length, files: clearedFiles })
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  } finally {
    graphMemoryClearingId.value = ''
  }
}

watch(
  () => [selectedNodeId.value, currentGraphId.value, memoryMode.value] as const,
  async ([, , mode]) => {
    if (mode === 'agent') {
      memoryAutoScroll.value = true
      beginAgentSelection()
      void refreshCliSessions()
      return
    }

    resetCliSessions()
    stopLoading()

    if (mode === 'graph') {
      memoryTitle.value = `Graph · ${currentGraphName.value || currentGraphId.value || ''}`
      graphWorkingPathInput.value = currentGraphWorkingPath.value
    }
  },
  { immediate: true },
)

watch(
  () => memoryRefreshRequest.value,
  async () => {
    if (memoryMode.value !== 'agent') return
    if (!hasSelectedNodeTarget()) return
    void refreshCliSessions()
    await loadAgentMemory()
  },
)

watch(
  () => [memoryMessages.value.length, memoryMeta.value] as const,
  () => {
    if (!cliSessionState.value?.supported || memoryMode.value !== 'agent') return
    void refreshCliSessions()
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

watch([memoryText, memoryMessages, memoryLiveMessage, memoryThinkingMessage, memoryActivityBlocks], () => {
  scheduleAutoScroll()
})

watch(
  () => memoryInteractiveSessionId.value,
  (sessionId) => {
    if (!sessionId) return
    scheduleAutoScroll(true)
  },
)

onBeforeUnmount(() => {
  if (autoScrollFrame != null) window.cancelAnimationFrame(autoScrollFrame)
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
      :closable="props.closable === true"
      @clear-memory="clearSelectedNodeMemory"
      @toggle-file-mode="toggleFileMode"
      @close="emit('close')"
    />

    <CliSessionPicker
      v-if="cliSessionState?.supported"
      :sessions="cliSessionState.sessions"
      :session-label="cliSessionState.session_label"
      :active-session-id="cliSessionState.active_session_id"
      :is-new-session="cliSessionState.is_new_session"
      :loading="cliSessionLoading"
      @select="chooseCliSession"
      @refresh="refreshCliSessions"
    />

    <MemoryContentView
      ref="contentViewRef"
      v-model:memory-text="memoryText"
      v-model:graph-name-input="graphNameInput"
      :graph-working-path-input="graphWorkingPathInput"
      :mode="memoryMode"
      :messages="structuredMessages"
      :live-message="memoryLiveMessage"
      :thinking-message="memoryThinkingMessage"
      :activity-message="memoryActivityMessage"
      :activity-blocks="memoryActivityBlocks"
      :node-id="String(selectedNodeId || '')"
      :graph-id="currentGraphId || 'default'"
      :markdown-preview="isMarkdownPreview"
      :word-wrap="isWordWrap"
      :show-line-numbers="showLineNumbers"
      :agent-images="agentImages"
      :rendered-markdown="renderedMarkdown"
      :graph-loading="graphLoading"
      :graph-memory-clearing-id="graphMemoryClearingId"
      :graphs="graphs"
      :graph-profiles="graphProfiles"
      :selected-graph-profile-id="selectedGraphProfileId"
      :interactive-session-id="memoryInteractiveSessionId"
      :interactive-input-disabled="!canSendInteractiveInput"
      :interactive-sending="memoryInteractiveSending"
      :interactive-input-text="interactiveInputText"
      :load-turn-details="loadTurnDetails"
      @save-current-file="saveCurrentFile"
      @save-graph-config="saveGraphConfig"
      @save-graph-profile="saveGraphProfile"
      @create-graph-from-profile="createGraphConfigFromProfile"
      @delete-graph-profile="deleteSelectedGraphProfile"
      @refresh-graphs="refreshGraphs"
      @load-graph-config="loadGraphConfig"
      @navigate-graph-node="navigateToGraphNode"
      @navigate-graph-group="navigateToGraphGroup"
      @clear-graph-memory="clearGraphMemory"
      @delete-graph-config="deleteGraphConfig"
      @toggle-graph-visibility="toggleGraphVisibility"
      @graph-path-error="graphStatus = $event"
      @update:selected-graph-profile-id="selectedGraphProfileId = $event"
      @update:graph-working-path-input="updateGraphWorkingPath"
      @auto-scroll-change="memoryAutoScroll = $event"
      @save-message="openSaveMessageDialog"
      @copy-message="copyMessageText"
      @delete-message="deleteMemoryMessage"
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
  font-size: var(--theme-panel-memory-panel-font-body, 13px);
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
  font-size: var(--theme-panel-memory-panel-font-body, 13px);
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
  font-size: var(--theme-panel-memory-panel-font-ui, 12px);
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
