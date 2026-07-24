<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { type MessageEnvelope, type ResourceKind } from '../../api'
import { resolveDroppedPaths, resolvePastedImagePaths } from '../../composables/droppedPaths'
import { useAudioRecorder } from '../../composables/useAudioRecorder'
import { useGlobalState } from '../../composables/useGlobalState'
import { uploadFiles } from '../../uploadApi'
import { AgentBoardKey } from './context'
import NodeEditorInputSection from './NodeEditorInputSection.vue'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected

const {
  lastError,
  nodeEditorInputText,
  nodeEditorAttachments,
  nodeEditorAttachmentDrafts,
  nodeTriggerInputs,
  nodeConfigDockWidth,
} = useGlobalState()

const isUploadingFiles = ref(false)
const audioRecorder = useAudioRecorder()
const goalArmedByNode = ref<Record<string, boolean>>({})

const selectedNode = computed(() => {
  const id = String(ctx.selectedNodeId.value || '').trim()
  if (!id) return null
  return ctx.nodes.value.find((item) => item.id === id) || null
})

const selectedConfig = computed(() => {
  const id = selectedNode.value?.id
  if (!id) return null
  return ctx.nodeConfigs.value[id] || null
})

const hasSelectedNode = computed(() => !!selectedNode.value)
const canSend = computed(() => hasSelectedNode.value)
const isNodeRunning = computed(() => (selectedNode.value ? ctx.isNodeRunning(selectedNode.value.id) : false))
const isStopRequested = computed(() => {
  const id = String(selectedNode.value?.id || '').trim()
  return !!(id && ctx.nodeConfigs.value[id]?._stop_requested)
})
const selectedGoalState = computed(() => {
  const state = selectedConfig.value?.goal_state
  return state && typeof state === 'object' ? state as Record<string, unknown> : null
})
const selectedGoalText = computed(() => String(selectedConfig.value?.goal || '').trim())
const hasPersistedGoal = computed(() => !!(selectedGoalText.value || selectedGoalState.value))
const isAgentNode = computed(() => selectedNode.value?.typeId === 'agent_node')
const audioInputEnabled = computed(() => isAgentNode.value)
const goalEnabled = computed(() => isAgentNode.value || hasPersistedGoal.value)
const goalActive = computed(() => {
  const id = String(selectedNode.value?.id || '').trim()
  return goalEnabled.value && (!!(id && goalArmedByNode.value[id]) || hasPersistedGoal.value)
})
const goalTitle = computed(() => {
  const status = String(selectedGoalState.value?.status || '').trim()
  const reason = String(selectedGoalState.value?.reason || '').trim()
  if (selectedGoalText.value) {
    return reason ? `Goal ${status || 'set'}: ${reason}` : `Goal ${status || 'set'}`
  }
  if (!isAgentNode.value) return 'Goal mode is available on Agent nodes'
  return goalActive.value ? 'Disable goal mode' : 'Enable goal mode'
})

function resetEditorInput() {
  nodeEditorInputText.value = ''
  nodeEditorAttachments.value = []
}

function rememberEditorInput(nodeId: string | null | undefined) {
  const id = String(nodeId || '').trim()
  if (!id) return
  nodeTriggerInputs.value = {
    ...nodeTriggerInputs.value,
    [id]: String(nodeEditorInputText.value || ''),
  }
  nodeEditorAttachmentDrafts.value = {
    ...nodeEditorAttachmentDrafts.value,
    [id]: nodeEditorAttachments.value.map((attachment) => ({ ...attachment })),
  }
}

function loadEditorInput(nodeId: string | null | undefined) {
  const id = String(nodeId || '').trim()
  nodeEditorInputText.value = id ? String(nodeTriggerInputs.value[id] || '') : ''
  nodeEditorAttachments.value = id
    ? (nodeEditorAttachmentDrafts.value[id] || []).map((attachment) => ({ ...attachment }))
    : []
}

function appendAttachment(path: string, name = '', kind = '', mime = '') {
  const safePath = String(path || '').trim()
  const safeName = String(name || '').trim() || safePath
  if (!safePath) return
  if (nodeEditorAttachments.value.some((item) => item.path === safePath)) return
  nodeEditorAttachments.value.push({ path: safePath, name: safeName, kind, mime })
}

function removeAttachment(index: number) {
  nodeEditorAttachments.value.splice(index, 1)
}

async function handleInputDrop(event: DragEvent) {
  event.preventDefault()
  isUploadingFiles.value = true
  try {
    const dropped = await resolveDroppedPaths(event, 'node-input-dock-input')
    for (const item of dropped) {
      appendAttachment(item.path, item.name)
    }
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  } finally {
    isUploadingFiles.value = false
  }
}

async function handleInputPaste(event: ClipboardEvent) {
  const hasImage = Array.from(event.clipboardData?.items || []).some(
    (item) => item.kind === 'file' && item.type.toLowerCase().startsWith('image/'),
  )
  if (!hasImage) return

  event.preventDefault()
  isUploadingFiles.value = true
  try {
    const pasted = await resolvePastedImagePaths(event, 'node-input-dock-paste')
    for (const item of pasted) {
      appendAttachment(item.path, item.name)
    }
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  } finally {
    isUploadingFiles.value = false
  }
}

function guessResourceKind(path: string): ResourceKind | 'file' {
  const lower = String(path || '').toLowerCase()
  if (/\.(png|jpg|jpeg|webp|gif|bmp|svg)$/.test(lower)) return 'image'
  if (/\.(mp4|mov|mkv|webm|avi|flv|m4v)$/.test(lower)) return 'video'
  if (/\.(mp3|wav|ogg|flac|m4a)$/.test(lower)) return 'audio'
  if (/\.(pdf|doc|docx|ppt|pptx|xls|xlsx|txt|md)$/.test(lower)) return 'doc'
  return 'file'
}

function attachmentResourceKind(file: { path: string; kind?: string; mime?: string }): ResourceKind | 'file' {
  const declared = String(file.kind || '').trim().toLowerCase()
  if (['image', 'video', 'audio', 'doc', 'url'].includes(declared)) return declared as ResourceKind
  if (String(file.mime || '').toLowerCase().startsWith('audio/')) return 'audio'
  return guessResourceKind(file.path)
}

async function toggleAudioRecording() {
  lastError.value = null
  try {
    if (!audioRecorder.recording.value) {
      await audioRecorder.start()
      return
    }
    const file = await audioRecorder.stop()
    isUploadingFiles.value = true
    const uploaded = await uploadFiles([file], 'node-input-audio-recording')
    for (const item of uploaded.files || []) {
      appendAttachment(item.path, item.name, 'audio', item.mime || file.type)
    }
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  } finally {
    isUploadingFiles.value = false
  }
}

function composePayload(): string | MessageEnvelope {
  const text = nodeEditorInputText.value.trim()
  if (!nodeEditorAttachments.value.length) {
    if (text) return text
    return { role: 'user', parts: [] }
  }
  const parts: MessageEnvelope['parts'] = []
  if (text) {
    parts.push({ type: 'text', text })
  }
  for (const file of nodeEditorAttachments.value) {
    const uri = String(file.path || '').trim()
    if (!uri) continue
    parts.push({
      type: 'resource',
      resource: {
        uri,
        name: String(file.name || ''),
        kind: attachmentResourceKind(file),
        mime: String(file.mime || ''),
        source: 'node_editor',
      },
    })
  }
  return { role: 'user', parts }
}

function payloadGoalText(payload: string | MessageEnvelope) {
  if (typeof payload === 'string') return payload.trim()
  const parts = Array.isArray(payload?.parts) ? payload.parts : []
  const texts: string[] = []
  for (const part of parts) {
    if (!part || typeof part !== 'object') continue
    if (part.type === 'text') {
      const text = String((part as any).text || '').trim()
      if (text) texts.push(text)
    } else if (part.type === 'resource') {
      const resource = (part as any).resource
      const uri = String(resource?.uri || '').trim()
      if (uri) texts.push(`[${String(resource?.kind || 'file')}] ${uri}`)
    } else if (part.type === 'structured') {
      texts.push(JSON.stringify((part as any).data))
    }
  }
  return texts.join('\n').trim()
}

async function persistGoalForSend(nodeId: string, payload: string | MessageEnvelope) {
  if (!goalActive.value || !isAgentNode.value) return
  const objective = payloadGoalText(payload)
  if (!objective) {
    throw new Error('Goal mode requires non-empty input.')
  }
  await ctx.setNodeFields(nodeId, {
    goal: objective,
    goal_state: {
      status: 'active',
      reason: 'Goal started from node input.',
      turn_count: 0,
      updated_at: new Date().toISOString(),
    },
  })
}

async function toggleGoal() {
  const nodeId = selectedNode.value?.id
  if (!nodeId) return
  if (!goalEnabled.value) return
  lastError.value = null
  try {
    if (goalActive.value) {
      goalArmedByNode.value = { ...goalArmedByNode.value, [nodeId]: false }
      await ctx.clearNodeFields(nodeId, ['goal', 'goal_state'])
    } else {
      goalArmedByNode.value = { ...goalArmedByNode.value, [nodeId]: true }
    }
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
}

async function sendMessage() {
  const nodeId = selectedNode.value?.id
  if (!nodeId || !canSend.value) return
  const payload = composePayload()
  lastError.value = null
  try {
    await persistGoalForSend(nodeId, payload)
    await ctx.sendNodeMessage(nodeId, payload)
    if (String(ctx.selectedNodeId.value || '') === nodeId) {
      resetEditorInput()
    }
    nodeTriggerInputs.value = { ...nodeTriggerInputs.value, [nodeId]: '' }
    nodeEditorAttachmentDrafts.value = { ...nodeEditorAttachmentDrafts.value, [nodeId]: [] }
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  }
}

watch(
  () => ctx.selectedNodeId.value,
  async (nodeId, prevNodeId) => {
    if (String(nodeId || '') === String(prevNodeId || '')) return
    rememberEditorInput(prevNodeId)
    loadEditorInput(nodeId)
  },
  { immediate: true },
)
</script>

<template>
  <section
    v-if="selectedNode"
    class="node-input-dock"
    data-board-occlusion="bottom"
    :style="{ left: `${nodeConfigDockWidth}px` }"
    @pointerdown.stop
    @click.stop
  >
    <NodeEditorInputSection
      v-model:input-text="nodeEditorInputText"
      :attachments="nodeEditorAttachments"
      :can-send="canSend"
      :is-uploading-files="isUploadingFiles"
      :goal-active="goalActive"
      :goal-enabled="goalEnabled"
      :goal-title="goalTitle"
      :audio-input-enabled="audioInputEnabled"
      :audio-recording="audioRecorder.recording.value"
      :audio-recording-supported="audioRecorder.supported.value"
      @drop-input="handleInputDrop"
      @paste-input="handleInputPaste"
      @remove-attachment="removeAttachment"
      @toggle-goal="toggleGoal"
      @toggle-audio-recording="toggleAudioRecording"
      @send="sendMessage"
    />
    <button v-if="isNodeRunning" type="button" class="stop-btn" @click="ctx.stopNodeWork(selectedNode.id).catch(() => null)">
      {{ isStopRequested ? 'Stopping' : 'Stop' }}
    </button>
  </section>
</template>

<style scoped>
.node-input-dock {
  position: absolute;
  right: var(--right-panel-width, 0px);
  bottom: 0;
  z-index: 70;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  box-sizing: border-box;
  max-height: 24vh;
  overflow: auto;
  padding: 8px 10px;
  border-top: 1px solid var(--theme-panel-node-side-editor-border-color, rgba(148, 163, 184, 0.24));
  background-color: var(--theme-panel-node-side-editor-background-color, rgba(2, 6, 23, 0.96));
  background-image: var(--theme-panel-node-side-editor-background-image, none);
  background-size: var(--theme-panel-node-side-editor-background-size, cover);
  background-position: var(--theme-panel-node-side-editor-background-position, center);
  background-repeat: var(--theme-panel-node-side-editor-background-repeat, no-repeat);
  background-blend-mode: var(--theme-panel-node-side-editor-background-blend-mode, normal);
  box-shadow: 0 -12px 28px rgba(15, 23, 42, 0.24);
}

.node-input-dock :deep(.input-section) {
  flex: 1 1 auto;
  min-width: 0;
  width: auto;
}

.stop-btn {
  flex: 0 0 auto;
  border: 1px solid rgba(248, 113, 113, 0.35);
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.2);
  color: var(--theme-panel-node-side-editor-button-text, #f8fafc);
  padding: 6px 10px;
  cursor: pointer;
}
</style>
