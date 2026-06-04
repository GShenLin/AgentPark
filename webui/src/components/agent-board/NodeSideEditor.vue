<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { type MessageEnvelope, type ResourceKind } from '../../api'
import { resolveDroppedPaths } from '../../composables/droppedPaths'
import { useGlobalState } from '../../composables/useGlobalState'
import { AgentBoardKey } from './context'
import NodeConfigSection from './NodeConfigSection.vue'
import NodeEditorInputSection from './NodeEditorInputSection.vue'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected

const { lastError, nodeEditorInputText, nodeEditorAttachments, providers, availableTools } = useGlobalState()

const CARD_WIDTH = 200
const PANEL_WIDTH = 360
const PANEL_GAP = 28
const PANEL_MAX_HEIGHT = 620

const isUploadingFiles = ref(false)
const isSubmitting = ref(false)

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
const canSend = computed(() => hasSelectedNode.value && !isSubmitting.value && !isUploadingFiles.value)
const isNodeRunning = computed(() => (selectedNode.value ? ctx.isNodeRunning(selectedNode.value.id) : false))

const panelStyle = computed(() => {
  const node = selectedNode.value
  if (!node) return { display: 'none' }
  const preferRight = node.ui.x + CARD_WIDTH + PANEL_GAP + PANEL_WIDTH <= ctx.canvasWidth.value - 20
  const left = preferRight
    ? node.ui.x + CARD_WIDTH + PANEL_GAP
    : Math.max(0, node.ui.x - PANEL_WIDTH - PANEL_GAP)
  const maxTop = Math.max(0, ctx.canvasHeight.value - PANEL_MAX_HEIGHT)
  const top = Math.max(0, Math.min(node.ui.y, maxTop))
  return {
    left: `${left}px`,
    top: `${top}px`,
  }
})

function resetEditorInput() {
  nodeEditorInputText.value = ''
  nodeEditorAttachments.value = []
}

function appendAttachment(path: string, name = '') {
  const safePath = String(path || '').trim()
  const safeName = String(name || '').trim() || safePath
  if (!safePath) return
  if (nodeEditorAttachments.value.some((item) => item.path === safePath)) return
  nodeEditorAttachments.value.push({ path: safePath, name: safeName })
}

function removeAttachment(index: number) {
  nodeEditorAttachments.value.splice(index, 1)
}

function clearAttachments() {
  nodeEditorAttachments.value = []
}

async function handleInputDrop(event: DragEvent) {
  event.preventDefault()
  isUploadingFiles.value = true
  try {
    const dropped = await resolveDroppedPaths(event, 'node-side-editor-input')
    for (const item of dropped) {
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
        kind: guessResourceKind(uri),
        source: 'node_editor',
      },
    })
  }
  return { role: 'user', parts }
}

async function sendMessage() {
  const nodeId = selectedNode.value?.id
  if (!nodeId || !canSend.value) return
  isSubmitting.value = true
  lastError.value = null
  try {
    await ctx.sendNodeMessage(nodeId, composePayload())
    resetEditorInput()
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  } finally {
    isSubmitting.value = false
  }
}

function showEditorError(message: string) {
  lastError.value = String(message || '').trim() || null
}

watch(
  () => ctx.selectedNodeId.value,
  async (nodeId, prevNodeId) => {
    if (String(nodeId || '') !== String(prevNodeId || '')) {
      resetEditorInput()
    }
  },
  { immediate: true },
)
</script>

<template>
  <aside
    v-if="selectedNode"
    class="node-side-editor"
    :style="panelStyle"
    @pointerdown.stop
    @click.stop
    @dragover.prevent
  >
    <div class="editor-head">
      <div class="editor-title-wrap">
        <div class="editor-title">{{ selectedNode.name }}</div>
        <div class="editor-sub">{{ selectedNode.typeId }} / {{ selectedNode.id }}</div>
      </div>
      <button v-if="isNodeRunning" class="head-btn danger" @click="ctx.stopNodeWork(selectedNode.id)">Stop</button>
    </div>

    <NodeEditorInputSection
      v-model:input-text="nodeEditorInputText"
      :attachments="nodeEditorAttachments"
      :can-send="canSend"
      :is-submitting="isSubmitting"
      :is-uploading-files="isUploadingFiles"
      @drop-input="handleInputDrop"
      @remove-attachment="removeAttachment"
      @clear-attachments="clearAttachments"
      @send="sendMessage"
    />

    <NodeConfigSection
      :node="selectedNode"
      :config="selectedConfig"
      :providers="providers"
      :available-tools="availableTools"
      @error="showEditorError"
    />
  </aside>
</template>

<style scoped>
.node-side-editor {
  position: absolute;
  z-index: 100;
  pointer-events: auto;
  width: 360px;
  max-height: 620px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(2, 6, 23, 0.96);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.34);
  backdrop-filter: blur(14px);
  isolation: isolate;
}

.editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.editor-head,
.section-divider {
  flex: 0 0 auto;
}

.editor-title-wrap {
  display: flex;
  flex-direction: column;
}

.editor-title {
  font-size: 16px;
  font-weight: 700;
  color: #f8fafc;
}

.editor-sub {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.84);
}

.head-btn {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.9);
  color: #f8fafc;
  padding: 8px 12px;
  cursor: pointer;
  position: relative;
  z-index: 2;
}

.head-btn {
  padding: 6px 10px;
  font-size: 12px;
}

.head-btn.danger {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(248, 113, 113, 0.35);
}
</style>
