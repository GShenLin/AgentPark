<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watchEffect } from 'vue'
import { AgentBoardKey, type NodeCard } from './context'
import NodeOutputRoutesSection from './NodeOutputRoutesSection.vue'

const props = defineProps<{
  node: NodeCard
}>()

const CARD_WIDTH = 230
const CARD_HEIGHT = 250
const PANEL_WIDTH = CARD_WIDTH
const PANEL_MIN_WIDTH = CARD_WIDTH
const PANEL_MAX_WIDTH = 520
const PANEL_GAP = 14
const CANVAS_PADDING = 80

type ResizeHandle = 'left' | 'right'
type ResizeSession = {
  handle: ResizeHandle
  startX: number
  startWidth: number
}

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected
const panelEl = ref<HTMLElement | null>(null)
const panelSize = ref({ width: PANEL_WIDTH })
const measuredPanelHeight = ref(0)
const resizeSession = ref<ResizeSession | null>(null)
let resizeObserver: ResizeObserver | null = null

const panelNode = computed(() => props.node)

const panelPosition = computed(() => {
  const node = panelNode.value
  const desiredLeft = node.ui.x + CARD_WIDTH / 2 - panelSize.value.width / 2
  const maxLeft = Math.max(0, ctx.canvasWidth.value - panelSize.value.width - CANVAS_PADDING / 2)
  return {
    left: Math.max(0, Math.min(maxLeft, desiredLeft)),
    top: node.ui.y + CARD_HEIGHT + PANEL_GAP,
  }
})

const panelStyle = computed(() => ({
  left: `${panelPosition.value.left}px`,
  top: `${panelPosition.value.top}px`,
  width: `${panelSize.value.width}px`,
}))

watchEffect(() => {
  const node = panelNode.value
  const right = Math.max(node.ui.x + CARD_WIDTH, panelPosition.value.left + panelSize.value.width)
  const bottom = panelPosition.value.top + measuredPanelHeight.value
  ctx.canvasWidth.value = Math.max(ctx.canvasWidth.value, Math.ceil(right + CANVAS_PADDING))
  ctx.canvasHeight.value = Math.max(ctx.canvasHeight.value, Math.ceil(bottom + CANVAS_PADDING))
})

watchEffect((onCleanup) => {
  const element = panelEl.value
  if (!element) return
  resizeObserver?.disconnect()
  resizeObserver = new ResizeObserver((entries) => {
    const entry = entries[0]
    if (!entry) return
    measuredPanelHeight.value = Math.ceil(entry.contentRect.height)
  })
  resizeObserver.observe(element)
  measuredPanelHeight.value = Math.ceil(element.getBoundingClientRect().height)
  onCleanup(() => {
    resizeObserver?.disconnect()
    resizeObserver = null
  })
})

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function resizeCursor(handle: ResizeHandle) {
  return handle === 'left' || handle === 'right' ? 'ew-resize' : ''
}

function stopPanelResize() {
  if (!resizeSession.value) return
  resizeSession.value = null
  window.removeEventListener('pointermove', onPanelResizeMove)
  window.removeEventListener('pointerup', stopPanelResize)
  window.removeEventListener('blur', stopPanelResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

function onPanelResizeMove(event: PointerEvent) {
  const session = resizeSession.value
  if (!session) return
  const scale = ctx.canvasScale.value || 1
  const dx = (event.clientX - session.startX) / scale

  const nextWidth =
    session.handle === 'right'
      ? session.startWidth + dx
      : session.handle === 'left'
        ? session.startWidth - dx
        : session.startWidth

  panelSize.value = {
    width: clamp(nextWidth, PANEL_MIN_WIDTH, PANEL_MAX_WIDTH),
  }
  event.preventDefault()
}

function startPanelResize(handle: ResizeHandle, event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  event.stopPropagation()
  resizeSession.value = {
    handle,
    startX: event.clientX,
    startWidth: panelSize.value.width,
  }
  document.body.style.cursor = resizeCursor(handle)
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', onPanelResizeMove)
  window.addEventListener('pointerup', stopPanelResize)
  window.addEventListener('blur', stopPanelResize)
}

onBeforeUnmount(stopPanelResize)
</script>

<template>
  <aside
    ref="panelEl"
    class="node-output-routes-panel"
    :style="panelStyle"
    @pointerdown.stop
    @click.stop
  >
    <NodeOutputRoutesSection :node="panelNode" />
    <div class="resize-handle resize-handle-left" @pointerdown="startPanelResize('left', $event)"></div>
    <div class="resize-handle resize-handle-right" @pointerdown="startPanelResize('right', $event)"></div>
  </aside>
</template>

<style scoped>
.node-output-routes-panel {
  position: absolute;
  z-index: 90;
  box-sizing: border-box;
  pointer-events: auto;
  padding: 14px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 12px;
  background: rgba(2, 6, 23, 0.96);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.3);
  backdrop-filter: blur(14px);
}

.resize-handle {
  position: absolute;
  z-index: 20;
  pointer-events: auto;
}

.resize-handle::before {
  content: '';
  position: absolute;
  background: transparent;
  transition: background 0.12s ease;
}

.resize-handle:hover::before,
.resize-handle:active::before {
  background: var(--accent-blue);
}

.resize-handle-left,
.resize-handle-right {
  top: 10px;
  bottom: 18px;
  width: 3px;
  cursor: ew-resize;
}

.resize-handle-left {
  left: 0;
}

.resize-handle-right {
  right: 0;
}

.resize-handle-left::before,
.resize-handle-right::before {
  inset: 0;
}

.resize-handle-left::after,
.resize-handle-right::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: -8px;
  right: -8px;
}

</style>
