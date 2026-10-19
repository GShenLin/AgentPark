<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { AgentBoardKey, type AgentBoardContext, type NodeCard } from './context'
import { edgeResizeCursor, edgeResizeSize, type EdgeResizeHandle } from './edgeResize'
import VoiceCallButton from '../../voice/VoiceCallButton.vue'
import NodeAgentMeta from './NodeAgentMeta.vue'
import NodeClockCountdown from './NodeClockCountdown.vue'
import NodeFloatingNote from './NodeFloatingNote.vue'
import NodeRuntimeDiagnostics from './NodeRuntimeDiagnostics.vue'
import { createWindowPointerDrag } from './pointerDrag'
import ToolActivityBadge from './ToolActivityBadge.vue'
import DangerButton from '../DangerButton.vue'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import MemoryResourcePart from '../MemoryResourcePart.vue'
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
import { t } from '../../i18n'
import { useNodeUnread } from '../../composables/useNodeUnread'

const injectedCtx = inject(AgentBoardKey)
if (!injectedCtx) {
  throw new Error('AgentBoard context not found')
}
const ctx: AgentBoardContext = injectedCtx

const props = defineProps<{
  node: NodeCard
  detached?: boolean
}>()
const emit = defineEmits<{ activate: []; minimize: []; close: [] }>()
const nodeUnread = useNodeUnread()
const unreadReceipt = computed(() => nodeUnread.receipt(ctx.currentGraphId.value || 'default', props.node.id))

const endpointId = computed(() => props.node.id)
const isAgentNode = computed(() => String(props.node.typeId || '') === 'agent_node')
const donePulse = computed(() => ctx.nodeDonePulse.value[props.node.id] || 0)
const isDone = computed(() => !!ctx.nodeDonePulse.value[props.node.id])
const isClockNode = computed(() => ctx.isClockNode(props.node.id))
const isClockRunning = computed(() => ctx.isClockRunning(props.node.id))
const isNodeRunning = computed(() => ctx.isNodeRunning(endpointId.value))
const isStopRequested = computed(() => !!ctx.nodeConfigs.value[endpointId.value]?._stop_requested)
const isPaused = computed(() => ctx.isNodeStopped(endpointId.value))
const clockStartLabel = computed(() => (ctx.isNodeStopped(endpointId.value) ? t('board.resume') : t('board.start')))
const previewText = computed(() => ctx.previewMessage(props.node.last_message))
const previewImageResource = computed(() => (
  (props.node.lastOutputResources || []).find((part) => (
    String((part as any)?.resource?.kind || '').trim().toLowerCase() === 'image'
  )) || null
))
const hasPreview = computed(() => (
  !!previewImageResource.value
  || !!String(previewText.value || '').trim()
))

const isEditingName = computed(() => ctx.renamingNodeId.value === props.node.id)
const editingName = ref('')
const nameInputRef = ref<InstanceType<typeof FormTextInput> | null>(null)
type ResizeHandle = Extract<EdgeResizeHandle, 'right' | 'bottom' | 'bottom-right'>
type ResizeSession = {
  handle: ResizeHandle
  pointerId: number
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

watch(isEditingName, (editing) => {
  if (!editing) return
  editingName.value = String(props.node.name || props.node.id)
  void nextTick(() => {
    nameInputRef.value?.focus()
    nameInputRef.value?.select()
  })
})

async function commitEditName() {
  if (!isEditingName.value) return
  const value = String(editingName.value || '').trim()
  ctx.finishNodeRename(props.node.id)
  if (!ctx) return
  await ctx.renameNodeCard(props.node.id, value || props.node.id).catch(() => null)
}

function cancelEditName() {
  ctx.finishNodeRename(props.node.id)
  editingName.value = String(props.node.name || props.node.id)
}

function selectItemOnly() {
  if (props.detached) { emit('activate'); return }
  if (Date.now() < ctx.suppressClickUntil.value) return
  ctx.selectAndFocusNode(props.node.id).catch(() => null)
}

const nodeResizeDrag = createWindowPointerDrag<ResizeSession>({
  session: resizeSession,
  getPointerId: (session) => session.pointerId,
  getScale: () => ctx.canvasScale.value,
  cursor: (session) => edgeResizeCursor(session.handle),
  onMove: (_event, delta, session) => {
    const { width, height } = edgeResizeSize(session, delta, {
      minWidth: NODE_CARD_MIN_WIDTH,
      maxWidth: NODE_CARD_MAX_WIDTH,
      minHeight: NODE_CARD_MIN_HEIGHT,
      maxHeight: NODE_CARD_MAX_HEIGHT,
    })
    ctx.resizeNodeCard(props.node.id, { width, height }, { persist: false })
  },
  onEnd: () => {
    ctx.suppressClickUntil.value = Date.now() + 200
    void ctx.resizeNodeCard(
      props.node.id,
      { width: nodeCardWidth(props.node), height: nodeCardHeight(props.node) },
      { persist: true },
    )
  },
})

function startNodeResize(handle: ResizeHandle, event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  event.stopPropagation()
  ctx.cancelBoardViewportScroll()
  nodeResizeDrag.start({
    handle,
    pointerId: event.pointerId,
    startWidth: nodeCardWidth(props.node) || NODE_CARD_DEFAULT_WIDTH,
    startHeight: nodeCardHeight(props.node) || NODE_CARD_DEFAULT_HEIGHT,
  }, event)
}

function stopNodeResize() {
  nodeResizeDrag.stop()
}

function cleanupNodeCard() {
  stopNodeResize()
  ctx.finishNodeRename(props.node.id)
}

onBeforeUnmount(cleanupNodeCard)
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
        resizing: resizeSession,
        'drop-target': ctx.dragHoverTargetId.value === endpointId,
        working: ctx.isNodeWorking(endpointId),
        running: ctx.isClockRunning(props.node.id),
        stopped: ctx.isNodeStopped(endpointId),
      },
    ]"
    :style="detached ? { ...ctx.itemStyle(endpointId), position: 'relative', left: 'auto', top: 'auto', width: '100%', height: '100%', transform: 'none' } : ctx.itemStyle(endpointId)"
    :data-board-item-id="endpointId"
    :data-agent-id="isAgentNode ? props.node.id : null"
    @click.capture="nodeUnread.acknowledge(ctx.currentGraphId.value || 'default', props.node.id, unreadReceipt)"
    @click="detached ? emit('activate') : ctx.onItemClick(endpointId, $event)"
    @pointerdown="!detached && ctx.onItemPointerDown(endpointId, $event)"
    @dragover.prevent.stop="ctx.onNodeCardDragOver(endpointId, $event)"
    @drop.prevent.stop="ctx.onNodeCardDrop(endpointId, $event)"
  >
    <button v-if="unreadReceipt" class="node-unread-badge" title="有新消息落盘，点击查看" aria-label="有新消息落盘" @pointerdown.stop @click.stop="selectItemOnly"></button>
    <NodeFloatingNote v-if="!detached" :note="ctx.nodeNotes.value[props.node.id]" />
    <!-- A conversation slot owns a live composer; completion must not remount it. -->
    <div class="node-card-inner" :key="$slots.content ? 'conversation' : donePulse" :class="{ done: isDone }">
      <div class="node-header">
        <FormTextInput
          v-if="isEditingName"
          ref="nameInputRef"
          v-model="editingName"
          class="node-title-input"
          compact
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
        >
          {{ props.node.name }}
        </div>
        <VoiceCallButton :node-id="props.node.id" :graph-id="ctx.currentGraphId.value || 'default'" status-only />
        <div v-if="isClockRunning" class="node-status-badge">{{ t('board.working') }}</div>
        <div v-if="props.node.remoteEnabled" class="node-status-badge" :title="props.node.remoteWorkerId">Remote</div>
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
          <button v-if="!isClockNode" type="button" class="node-pause" @pointerdown.stop @click.stop="ctx.toggleNodeStop(endpointId).catch(() => null)">
            {{ isPaused ? t('board.resume') : t('board.pause') }}
          </button>
          <button v-if="!isClockNode && isNodeRunning" type="button" class="node-stop" @pointerdown.stop @click.stop="ctx.stopNodeWork(endpointId).catch(() => null)">
            {{ isStopRequested ? t('common.stopping') : t('common.stop') }}
          </button>
          <ActionButton v-if="detached" icon compact aria-label="最小化小 Agent" title="最小化到任务栏"
            @pointerdown.stop @click.stop="emit('minimize')">
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 8h8" fill="none" stroke="currentColor" stroke-width="1.4" /></svg>
          </ActionButton>
          <DangerButton
            icon
            compact
            :aria-label="detached ? '关闭小 Agent' : t('board.deleteNode')"
            :title="detached ? '关闭小窗，Agent 继续运行' : t('board.deleteNode')"
            @pointerdown.stop
            @click.stop="detached ? emit('close') : ctx.deleteNodeCard(props.node.id).catch(() => null)"
          >
            ×
          </DangerButton>
        </div>
      </div>
      <slot name="content">
      <NodeAgentMeta v-if="isAgentNode" :mode="props.node.mode" :provider-id="props.node.providerId" />
      <div class="node-body">
        <div class="node-label">{{ isAgentNode ? t('board.lastReply') : t('board.lastMessage') }}</div>
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
        <MemoryResourcePart
          v-if="!isClockRunning && previewImageResource"
          class="node-output-resource"
          :part="previewImageResource"
          compact
          @pointerdown.stop
        />
        <NodeClockCountdown
          v-else-if="isClockRunning"
          :next-fire-at="ctx.nodeConfigs.value[props.node.id]?.['_clock_next_fire_at']"
          :fallback="previewText"
        />
        <div v-else class="node-message" :class="{ empty: !hasPreview }">
          {{ previewText || ' ' }}
        </div>
      </div>
      <button
        type="button"
        class="node-add-output"
        :title="t('board.addOutputRoute')"
        @pointerdown.stop
        @click.stop="ctx.addOutputRoute(props.node.id).catch(() => null)"
      >
        +
      </button>
      </slot>
      <template v-if="!detached">
        <div class="node-resize-handle node-resize-right" @pointerdown="startNodeResize('right', $event)"></div>
        <div class="node-resize-handle node-resize-bottom" @pointerdown="startNodeResize('bottom', $event)"></div>
        <div class="node-resize-handle node-resize-corner" @pointerdown="startNodeResize('bottom-right', $event)"></div>
      </template>
    </div>
  </div>
</template>

<style scoped src="./nodeCardItem.css"></style>
