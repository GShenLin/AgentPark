<script setup lang="ts">
import { computed, inject, ref, watchEffect } from 'vue'
import { AgentBoardKey } from './context'
import CanvasContextMenu from './CanvasContextMenu.vue'
import NodeContextMenu from './NodeContextMenu.vue'
import NodeCardItem from './NodeCardItem.vue'
import NodeOutputRoutesPanel from './NodeOutputRoutesPanel.vue'
import NodeSideEditor from './NodeSideEditor.vue'
import UserInteractionDialog from '../UserInteractionDialog.vue'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected

const boardEl = ref<HTMLElement | null>(null)
const canvasEl = ref<HTMLElement | null>(null)
const contextMenuRef = ref<{
  openAt: (screenPoint: { x: number; y: number }, boardPoint: { x: number; y: number }) => void
  closeMenu: () => void
} | null>(null)
const nodeContextMenuRef = ref<{
  openAt: (screenPoint: { x: number; y: number }, nodeId: string) => void
  closeMenu: () => void
} | null>(null)

const items = computed(() => ctx.nodes.value)
const nodesWithOutputRoutes = computed(() => {
  const sourceIds = new Set(ctx.links.value.map((link) => link.from.node))
  return ctx.nodes.value.filter((node) => sourceIds.has(node.id))
})

function getBoardPoint(event: MouseEvent) {
  const canvas = canvasEl.value
  if (!canvas) return { x: 0, y: 0 }
  const rect = canvas.getBoundingClientRect()
  const style = window.getComputedStyle(canvas)
  const paddingLeft = Number.parseFloat(style.paddingLeft || '0') || 0
  const paddingTop = Number.parseFloat(style.paddingTop || '0') || 0
  const scale = ctx.canvasScale.value || 1
  return {
    x: (event.clientX - rect.left - paddingLeft) / scale,
    y: (event.clientY - rect.top - paddingTop) / scale,
  }
}

function onBoardContextMenu(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  const nodeEl = target?.closest('.node-card') as HTMLElement | null
  event.preventDefault()
  if (nodeEl) {
    const nodeId = String(nodeEl.dataset.boardItemId || '').trim()
    if (nodeId) {
      nodeContextMenuRef.value?.openAt({ x: event.clientX, y: event.clientY }, nodeId)
    }
    return
  }
  contextMenuRef.value?.openAt({ x: event.clientX, y: event.clientY }, getBoardPoint(event))
}

watchEffect(() => {
  ctx.boardRef.value = boardEl.value
  ctx.canvasRef.value = canvasEl.value
})
</script>

<template>
  <div
    ref="boardEl"
    class="agent-board"
    :class="{ panning: ctx.panSession.value }"
    @mousedown.capture="ctx.onBoardMouseDownCapture"
    @wheel.capture="ctx.onBoardWheel"
    @dragover="ctx.onBoardDragOver"
    @drop="ctx.onBoardDrop"
    @contextmenu="onBoardContextMenu"
  >
    <div
      ref="canvasEl"
      class="agent-canvas"
      :style="{ width: `${ctx.canvasWidth.value * ctx.canvasScale.value}px`, height: `${ctx.canvasHeight.value * ctx.canvasScale.value}px` }"
    >
      <div class="canvas-content" :style="{ width: `${ctx.canvasWidth.value}px`, height: `${ctx.canvasHeight.value}px`, transform: `scale(${ctx.canvasScale.value})` }">
        <div
          v-if="ctx.selectionRect.value"
          class="selection-rect"
          :style="{
            left: `${ctx.selectionRect.value.x}px`,
            top: `${ctx.selectionRect.value.y}px`,
            width: `${ctx.selectionRect.value.width}px`,
            height: `${ctx.selectionRect.value.height}px`,
          }"
        ></div>

        <NodeCardItem
          v-for="node in items"
          :key="`node:${node.id}`"
          :node="node"
        />
        <NodeOutputRoutesPanel
          v-for="node in nodesWithOutputRoutes"
          :key="`routes:${node.id}`"
          :node="node"
        />
        <UserInteractionDialog
          :nodes="items"
          :canvas-width="ctx.canvasWidth.value"
          :canvas-height="ctx.canvasHeight.value"
        />
        <NodeSideEditor />
      </div>
    </div>
    <CanvasContextMenu ref="contextMenuRef" />
    <NodeContextMenu ref="nodeContextMenuRef" />
  </div>
</template>

<style scoped>
.agent-board {
  flex: 1;
  min-height: 0;
  overflow: auto;
  cursor: grab;
}

.agent-board.panning {
  cursor: grabbing;
}

.agent-canvas {
  position: relative;
  padding: 40px;
}

.canvas-content {
  position: relative;
  transform-origin: left top;
}

.selection-rect {
  position: absolute;
  border: 1px dashed rgba(125, 211, 252, 0.95);
  background: rgba(56, 189, 248, 0.16);
  pointer-events: none;
}

</style>
