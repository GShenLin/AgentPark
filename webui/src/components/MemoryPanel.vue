<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { clearNodeInstanceMemory, deleteGraph, deleteNodeInstanceMemoryMessage, listGraphs, loadGraph, saveGraph, setStartupGraphConfig, type GraphConfig, type GraphInfo, type MessageEnvelope } from '../api'
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
  memoryLiveMessage,
  memoryTitle,
  memoryMeta,
  memoryMode,
  memoryRefreshRequest,
  memoryLiveRefreshRequest,
  agentImages,
  selectedNodeId,
  graphSnapshot,
  graphLoadRequest,
  currentGraphId,
  currentGraphName,
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

const graphs = ref<GraphInfo[]>([])
const graphNameInput = ref('')
const graphStatus = ref<string | null>(null)
const graphLoading = ref(false)

const structuredMessages = computed(() => (Array.isArray(memoryMessages.value) ? memoryMessages.value : []))
const canClearMemory = computed(() => hasSelectedNodeTarget())

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
      await loadAgentMemory()
    }
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
}

async function deleteMemoryMessage(message: MessageEnvelope) {
  const nodeId = String(selectedNodeId.value || '').trim()
  const messageId = String((message as any)?.id || '').trim()
  if (!nodeId || !messageId) return
  const ok = window.confirm('Delete this conversation entry?')
  if (!ok) return
  try {
    await deleteNodeInstanceMemoryMessage(nodeId, messageId, currentGraphId.value || 'default')
    memoryMessages.value = memoryMessages.value.filter((item) => String((item as any)?.id || '') !== messageId)
    await loadAgentMemory()
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
}

const renderedMarkdown = computed(() => {
  return renderMemoryMarkdown(memoryText.value)
})

async function refreshGraphs() {
  graphLoading.value = true
  graphStatus.value = null
  try {
    graphs.value = await listGraphs()
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  } finally {
    graphLoading.value = false
  }
}

function resolveGraphName(snapshot: GraphConfig | null) {
  const raw = graphNameInput.value.trim() || currentGraphName.value || snapshot?.name || ''
  if (raw) return raw
  return `graph-${Date.now()}`
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
  }

  try {
    const result = await saveGraph(name, payload, {
      saveReason: 'memory_panel_save',
      sourceGraphId: sourceGraphId && sourceGraphId !== name ? sourceGraphId : undefined,
    })
    const savedAsNewGraph = !!sourceGraphId && sourceGraphId !== result.id
    currentGraphId.value = result.id
    currentGraphName.value = result.name
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

async function loadGraphConfig(item: GraphInfo) {
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
      memoryMode.value = 'graph'
      return
    }
    currentGraphId.value = res.id
    currentGraphName.value = res.name
    graphNameInput.value = res.name
    graphLoadRequest.value = res
    await setStartupGraphConfig(res.id, res.name).catch(() => null)
    memoryMode.value = 'graph'
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
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
      graphNameInput.value = 'default'
      graphLoadRequest.value = { id: 'default', name: 'default', nodes: [], links: [] }
      await setStartupGraphConfig('default', 'default').catch(() => null)
    }
    await refreshGraphs()
    graphStatus.value = `Graph deleted: ${name}`
  } catch (e: any) {
    graphStatus.value = String(e?.message || e)
  }
}

watch(
  () => selectedNodeId.value,
  async () => {
    if (memoryMode.value !== 'agent') return
    stopLoading()
    memoryAutoScroll.value = true
    await loadAgentMemory()
    startAgentLiveStream()
  },
)

watch(
  () => memoryMode.value,
  async (mode) => {
    stopLoading()

    if (mode === 'agent') {
      memoryAutoScroll.value = true
      await loadAgentMemory()
      startAgentLiveStream()
      return
    }

    if (mode === 'graph') {
      memoryTitle.value = currentGraphName.value || 'Graph'
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
      :mode="memoryMode"
      :messages="structuredMessages"
      :live-message="memoryLiveMessage"
      :markdown-preview="isMarkdownPreview"
      :word-wrap="isWordWrap"
      :show-line-numbers="showLineNumbers"
      :agent-images="agentImages"
      :rendered-markdown="renderedMarkdown"
      :graph-loading="graphLoading"
      :graphs="graphs"
      @save-current-file="saveCurrentFile"
      @save-graph-config="saveGraphConfig"
      @refresh-graphs="refreshGraphs"
      @load-graph-config="loadGraphConfig"
      @delete-graph-config="deleteGraphConfig"
      @auto-scroll-change="memoryAutoScroll = $event"
      @save-message="openSaveMessageDialog"
      @copy-message="copyMessageText"
      @delete-message="deleteMemoryMessage"
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
  background: rgba(2, 6, 23, 0.56);
  border: 1px solid rgba(148, 163, 184, 0.15);
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

</style>
