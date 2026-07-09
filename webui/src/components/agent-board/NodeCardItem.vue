<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { AgentBoardKey, type AgentBoardContext, type NodeCard } from './context'
import NodeAgentMeta from './NodeAgentMeta.vue'
import NodeRuntimeDiagnostics from './NodeRuntimeDiagnostics.vue'
import ToolActivityBadge from './ToolActivityBadge.vue'
import {
  NODE_CARD_DEFAULT_HEIGHT,
  NODE_CARD_DEFAULT_WIDTH,
  NODE_CARD_MAX_HEIGHT,
  NODE_CARD_MAX_WIDTH,
  NODE_CARD_MIN_HEIGHT,
  NODE_CARD_MIN_WIDTH,
  nodeCardHeight,
  nodeCardWidth,
} from './boardModel'

const injectedCtx = inject(AgentBoardKey)
if (!injectedCtx) {
  throw new Error('AgentBoard context not found')
}
const ctx: AgentBoardContext = injectedCtx

const props = defineProps<{
  node: NodeCard
}>()

const endpointId = computed(() => props.node.id)
const isAgentNode = computed(() => String(props.node.typeId || '') === 'agent_node')
const donePulse = computed(() => ctx.nodeDonePulse.value[props.node.id] || 0)
const isDone = computed(() => !!ctx.nodeDonePulse.value[props.node.id])
const isClockNode = computed(() => ctx.isClockNode(props.node.id))
const isClockRunning = computed(() => ctx.isClockRunning(props.node.id))
const isNodeRunning = computed(() => ctx.isNodeRunning(endpointId.value))
const isStopRequested = computed(() => !!ctx.nodeConfigs.value[endpointId.value]?._stop_requested)
const clockStartLabel = computed(() => (ctx.isNodeStopped(endpointId.value) ? 'Resume' : 'Start'))
const previewText = computed(() => ctx.previewMessage(props.node.last_message))
const hasPreview = computed(() => !!String(previewText.value || '').trim())

const isEditingName = ref(false)
const editingName = ref('')
const nameInputRef = ref<HTMLInputElement | null>(null)
type ResizeHandle = 'right' | 'bottom' | 'corner'
type ResizeSession = {
  handle: ResizeHandle
  pointerId: number
  startX: number
  startY: number
  startWidth: number
  startHeight: number
}
const resizeSession = ref<ResizeSession | null>(null)

watch(
  () => props.node.name || '',
  (value) => {
    if (!isEditingName.value) {
      editingName.value = String(value || '')
    }
  },
  { immediate: true },
)

function startEditName() {
  isEditingName.value = true
  editingName.value = String(props.node.name || props.node.id)
  void nextTick(() => {
    nameInputRef.value?.focus()
    nameInputRef.value?.select()
  })
}

async function commitEditName() {
  const value = String(editingName.value || '').trim()
  isEditingName.value = false
  if (!ctx) return
  await ctx.renameNodeCard(props.node.id, value || props.node.id).catch(() => null)
}

function cancelEditName() {
  isEditingName.value = false
  editingName.value = String(props.node.name || props.node.id)
}

function selectItemOnly() {
  if (Date.now() < ctx.suppressClickUntil.value) return
  ctx.selectNode(props.node.id)
  ctx.refreshNodeConfig(props.node.id).catch(() => null)
}

function openNodeFolder(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (target?.closest('button, input, textarea, select, a, .node-title, .port, .node-resize-handle')) return
  ctx.openNodeFolder(endpointId.value).catch(() => null)
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function startNodeResize(handle: ResizeHandle, event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  event.stopPropagation()
  resizeSession.value = {
    handle,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    startWidth: nodeCardWidth(props.node) || NODE_CARD_DEFAULT_WIDTH,
    startHeight: nodeCardHeight(props.node) || NODE_CARD_DEFAULT_HEIGHT,
  }
  const cursor = handle === 'right' ? 'ew-resize' : handle === 'bottom' ? 'ns-resize' : 'nwse-resize'
  document.body.style.cursor = cursor
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', onNodeResizeMove)
  window.addEventListener('pointerup', stopNodeResize)
  window.addEventListener('blur', stopNodeResize)
}

function onNodeResizeMove(event: PointerEvent) {
  const session = resizeSession.value
  if (!session || event.pointerId !== session.pointerId) return
  const scale = ctx.canvasScale.value || 1
  const dx = (event.clientX - session.startX) / scale
  const dy = (event.clientY - session.startY) / scale
  const width = session.handle === 'bottom' ? session.startWidth : clamp(session.startWidth + dx, NODE_CARD_MIN_WIDTH, NODE_CARD_MAX_WIDTH)
  const height = session.handle === 'right' ? session.startHeight : clamp(session.startHeight + dy, NODE_CARD_MIN_HEIGHT, NODE_CARD_MAX_HEIGHT)
  ctx.resizeNodeCard(props.node.id, { width, height }, { persist: false })
  event.preventDefault()
}

function stopNodeResize() {
  if (!resizeSession.value) return
  resizeSession.value = null
  ctx.suppressClickUntil.value = Date.now() + 200
  void ctx.resizeNodeCard(
    props.node.id,
    { width: nodeCardWidth(props.node), height: nodeCardHeight(props.node) },
    { persist: true },
  )
  window.removeEventListener('pointermove', onNodeResizeMove)
  window.removeEventListener('pointerup', stopNodeResize)
  window.removeEventListener('blur', stopNodeResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

onBeforeUnmount(stopNodeResize)
</script>

<template>
  <div
    :class="[
      'node-card',
      {
        'agent-card': isAgentNode,
        selected: endpointId === ctx.selectedNodeId.value,
        'multi-selected': ctx.isNodeSelected(endpointId),
        dragging: ctx.isDragging(endpointId),
        'drop-target': ctx.dragHoverTargetId.value === endpointId,
        working: ctx.isNodeWorking(endpointId),
        running: ctx.isClockRunning(props.node.id),
        stopped: ctx.isNodeStopped(endpointId),
      },
    ]"
    :style="ctx.itemStyle(endpointId)"
    :data-board-item-id="endpointId"
    :data-agent-id="isAgentNode ? props.node.id : null"
    @click="ctx.onItemClick(endpointId, $event)"
    @dblclick.stop.prevent="openNodeFolder"
    @pointerdown="ctx.onItemPointerDown(endpointId, $event)"
    @pointermove="ctx.onItemPointerMove"
    @pointerup="ctx.endDrag"
    @pointercancel="ctx.endDrag"
    @dragover.prevent.stop="ctx.onNodeCardDragOver(endpointId, $event)"
    @drop.prevent.stop="ctx.onNodeCardDrop(endpointId, $event)"
  >
    <div class="node-card-inner" :key="donePulse" :class="{ done: isDone }">
      <div class="node-header">
        <input
          v-if="isEditingName"
          ref="nameInputRef"
          v-model="editingName"
          class="node-title-input"
          type="text"
          @pointerdown.stop
          @click.stop
          @keydown.enter.prevent="commitEditName()"
          @keydown.esc.prevent="cancelEditName()"
          @blur="commitEditName()"
        />
        <div
          v-if="!isEditingName"
          class="node-title"
          @pointerdown.stop
          @click.stop="selectItemOnly()"
          @dblclick.stop.prevent="startEditName()"
        >
          {{ props.node.name }}
        </div>
        <div v-if="isClockRunning" class="node-status-badge">Working</div>
        <div class="node-actions">
          <button type="button" class="node-trigger" @pointerdown.stop @click.stop="ctx.triggerNode(endpointId).catch(() => null)">
            Trigger
          </button>
          <button v-if="isClockNode && !isClockRunning" type="button" class="node-start" @pointerdown.stop @click.stop="ctx.startClockNode(endpointId).catch(() => null)">
            {{ clockStartLabel }}
          </button>
          <button v-if="isClockNode && isClockRunning" type="button" class="node-pause" @pointerdown.stop @click.stop="ctx.toggleNodeStop(endpointId).catch(() => null)">
            Pause
          </button>
          <button v-if="!isClockNode && !isNodeRunning" type="button" class="node-pause" @pointerdown.stop @click.stop="ctx.toggleNodeStop(endpointId).catch(() => null)">
            {{ ctx.isNodeStopped(endpointId) ? 'Resume' : 'Pause' }}
          </button>
          <button v-if="!isClockNode && isNodeRunning" type="button" class="node-stop" @pointerdown.stop @click.stop="ctx.stopNodeWork(endpointId).catch(() => null)">
            {{ isStopRequested ? 'Stopping' : 'Stop' }}
          </button>
          <button
            class="node-delete"
            @pointerdown.stop
            @click.stop="ctx.deleteNodeCard(props.node.id).catch(() => null)"
          >
            x
          </button>
        </div>
      </div>
      <NodeAgentMeta v-if="isAgentNode" :mode="props.node.mode" :provider-id="props.node.providerId" />
      <div class="node-body">
        <div class="node-label">{{ isAgentNode ? 'Last reply' : 'Last message' }}</div>
        <ToolActivityBadge
          v-if="isAgentNode"
          :event="props.node.lastRuntimeEvent"
          :events="props.node.runtimeEvents"
          :calls="props.node.runtimeToolCalls"
        />
        <NodeRuntimeDiagnostics
          v-if="isAgentNode"
          :events="props.node.runtimeEvents"
          :provider-summaries="props.node.providerRequestSummaries"
          :provider-totals="props.node.providerRequestTotals"
          :runtime-tool-calls="props.node.runtimeToolCalls"
        />
        <div class="node-message" :class="{ empty: !hasPreview }">
          {{ previewText || ' ' }}
        </div>
      </div>
      <button
        type="button"
        class="node-add-output"
        title="Add output route"
        @pointerdown.stop
        @click.stop="ctx.addOutputRoute(props.node.id).catch(() => null)"
      >
        +
      </button>
      <div class="node-resize-handle node-resize-right" @pointerdown="startNodeResize('right', $event)"></div>
      <div class="node-resize-handle node-resize-bottom" @pointerdown="startNodeResize('bottom', $event)"></div>
      <div class="node-resize-handle node-resize-corner" @pointerdown="startNodeResize('corner', $event)"></div>
    </div>
  </div>
</template>

<style scoped>
.node-card {
  position: absolute;
  width: 230px;
  height: 250px;
  background-color: var(--theme-panel-node-card-background-color, rgba(15, 23, 42, 0.75));
  background-image: var(--theme-panel-node-card-background-image, none);
  background-size: var(--theme-panel-node-card-background-size, cover);
  background-position: var(--theme-panel-node-card-background-position, center);
  background-repeat: var(--theme-panel-node-card-background-repeat, no-repeat);
  background-blend-mode: var(--theme-panel-node-card-background-blend-mode, normal);
  border: 1px solid var(--theme-panel-node-card-border-color, rgba(148, 163, 184, 0.2));
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
  user-select: none;
  touch-action: none;
}

.node-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
  border-color: rgba(148, 163, 184, 0.3);
}

.node-card.agent-card {
  background-color: var(--theme-panel-node-card-background-color, rgba(30, 41, 59, 0.8));
  border: 1px solid var(--theme-panel-node-card-border-color, rgba(148, 163, 184, 0.1));
}

.node-card.agent-card:hover {
  background: rgba(30, 41, 59, 0.95);
}

.node-card.selected {
  border: 1px solid var(--theme-panel-node-card-border-selected, rgba(99, 102, 241, 0.5));
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.node-card.multi-selected:not(.selected) {
  border: 1px solid rgba(125, 211, 252, 0.7);
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.25);
}

.node-card.stopped {
  border-color: rgba(148, 163, 184, 0.35);
  background: rgba(15, 23, 42, 0.55);
}

.node-card.running:not(.working):not(.dragging) {
  border-color: rgba(34, 197, 94, 0.5);
  box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.16);
}

.node-card.dragging {
  cursor: grabbing;
  transition: none;
}

.node-card.drop-target {
  border: 1px solid rgba(52, 211, 153, 0.82);
  box-shadow: 0 0 0 2px rgba(52, 211, 153, 0.28), 0 12px 18px -8px rgba(16, 185, 129, 0.45);
}

.node-card-inner {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.node-card-inner.done {
  animation: node-done 420ms ease-out;
}

.node-pause {
  background: var(--theme-panel-node-card-button-background, rgba(125, 211, 252, 0.16));
  border: 1px solid var(--theme-panel-node-card-button-border, rgba(125, 211, 252, 0.35));
  color: var(--theme-panel-node-card-button-text, rgba(224, 242, 254, 0.95));
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  cursor: pointer;
}

.node-start {
  background: rgba(34, 197, 94, 0.16);
  border: 1px solid rgba(34, 197, 94, 0.35);
  color: rgba(220, 252, 231, 0.95);
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  cursor: pointer;
}

.node-start:hover {
  background: rgba(34, 197, 94, 0.26);
}

.node-trigger {
  background: rgba(52, 211, 153, 0.16);
  border: 1px solid rgba(52, 211, 153, 0.35);
  color: rgba(209, 250, 229, 0.95);
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  cursor: pointer;
}

.node-trigger:hover {
  background: rgba(52, 211, 153, 0.26);
}

.node-pause:hover {
  background: var(--theme-panel-node-card-button-hover-background, rgba(125, 211, 252, 0.26));
}

.node-header {
  padding: 12px 12px 6px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.node-title {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  font-size: 14px;
  color: var(--theme-panel-node-card-text-title, #fff);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-title-input {
  width: 96px;
  background: rgba(15, 23, 42, 0.85);
  border: 1px solid rgba(99, 102, 241, 0.6);
  color: #fff;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  padding: 3px 6px;
  outline: none;
}

.node-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  margin-left: auto;
  flex-shrink: 0;
}

.node-status-badge {
  margin-left: auto;
  background: rgba(34, 197, 94, 0.14);
  border: 1px solid rgba(34, 197, 94, 0.28);
  color: rgba(220, 252, 231, 0.95);
  font-size: 10px;
  line-height: 1;
  padding: 4px 6px;
  border-radius: 999px;
}


.node-delete {
  background: none;
  border: none;
  color: rgba(148, 163, 184, 0.6);
  cursor: pointer;
  padding: 0;
  font-size: 14px;
  line-height: 1;
}

.node-delete:hover {
  color: #ef4444;
}

.node-stop {
  background: rgba(239, 68, 68, 0.2);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #fecaca;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  cursor: pointer;
}

.node-stop:hover {
  background: rgba(239, 68, 68, 0.35);
}

.node-body {
  padding: 0 46px 42px 12px;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.node-label {
  font-size: 10px;
  color: var(--theme-panel-node-card-text-muted, rgba(148, 163, 184, 0.5));
  margin-bottom: 4px;
}

.node-message {
  flex: 1 1 auto;
  min-height: 0;
  font-size: 12px;
  color: var(--theme-panel-node-card-text-body, rgba(255, 255, 255, 0.7));
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.node-message.empty {
  color: var(--theme-panel-node-card-text-muted, rgba(148, 163, 184, 0.45));
}

.node-add-output {
  position: absolute;
  right: 10px;
  bottom: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--theme-panel-node-card-button-border, rgba(125, 211, 252, 0.36));
  border-radius: 8px;
  background: var(--theme-panel-node-card-button-background, rgba(14, 165, 233, 0.16));
  color: var(--theme-panel-node-card-button-text, rgba(224, 242, 254, 0.98));
  font-size: 18px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 8px 18px rgba(2, 132, 199, 0.16);
}

.node-add-output:hover {
  border-color: rgba(125, 211, 252, 0.58);
  background: var(--theme-panel-node-card-button-hover-background, rgba(14, 165, 233, 0.28));
}

.node-resize-handle {
  position: absolute;
  z-index: 3;
  background: transparent;
}

.node-resize-right {
  top: 0;
  right: 0;
  width: 12px;
  height: 100%;
  cursor: ew-resize;
}

.node-resize-bottom {
  left: 0;
  bottom: 0;
  width: 100%;
  height: 12px;
  cursor: ns-resize;
}

.node-resize-corner {
  right: 0;
  bottom: 0;
  width: 28px;
  height: 28px;
  cursor: nwse-resize;
}

@keyframes node-done {
  0% {
    transform: translateY(0);
  }
  32% {
    transform: translateY(-11px);
  }
  64% {
    transform: translateY(0);
  }
  82% {
    transform: translateY(5px);
  }
  100% {
    transform: translateY(0);
  }
}

</style>


