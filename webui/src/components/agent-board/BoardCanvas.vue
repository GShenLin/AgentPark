<script setup lang="ts">
import { computed, inject, ref, watchEffect } from 'vue'
import { AgentBoardKey } from './context'
import CanvasContextMenu from './CanvasContextMenu.vue'
import NodeCardItem from './NodeCardItem.vue'
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

const items = computed(() => ctx.nodes.value)

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
  const overItem = !!target?.closest('.node-card')
  event.preventDefault()
  if (overItem) return
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
        <svg
          class="agent-links"
          :width="ctx.canvasWidth.value"
          :height="ctx.canvasHeight.value"
          xmlns:xlink="http://www.w3.org/1999/xlink"
        >
        <path
          v-for="link in ctx.links.value"
          :key="link.id"
          class="agent-link"
          :id="`link-path-${link.id}`"
          :d="ctx.linkPath(link)"
        />
        <path v-if="ctx.linkSession.value" class="agent-link active" :d="ctx.activeLinkPath()" />
        <g v-for="flow in ctx.linkFlows.value" :key="flow.id">
          <circle
            v-for="(delay, index) in ctx.LINK_FLOW_BUBBLES"
            :key="`${flow.id}-${index}`"
            class="agent-link-bubble"
            :r="index % 2 === 0 ? 3.2 : 2.6"
            fill="#7dd3fc"
            opacity="0.85"
          >
            <animateMotion
              :dur="`${ctx.LINK_FLOW_DURATION_MS / 1000}s`"
              :begin="`${delay}s`"
              repeatCount="1"
              keySplines="0.4 0 0.2 1"
              calcMode="spline"
              keyTimes="0;1"
            >
              <mpath :href="`#link-path-${flow.linkId}`" :xlink:href="`#link-path-${flow.linkId}`" />
            </animateMotion>
          </circle>
        </g>
        </svg>

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
        <UserInteractionDialog
          :nodes="items"
          :canvas-width="ctx.canvasWidth.value"
          :canvas-height="ctx.canvasHeight.value"
        />
        <NodeSideEditor />
      </div>
    </div>
    <CanvasContextMenu ref="contextMenuRef" />
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

.agent-links {
  position: absolute;
  left: 0;
  top: 0;
  pointer-events: none;
}

.agent-link {
  fill: none;
  stroke: rgba(125, 211, 252, 0.6);
  stroke-width: 2;
}

.agent-link.active {
  stroke: rgba(99, 102, 241, 0.8);
  stroke-dasharray: 4 4;
}

.agent-link-bubble {
  filter: drop-shadow(0 0 6px rgba(125, 211, 252, 0.5));
}
</style>
