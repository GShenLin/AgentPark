<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref } from 'vue'
import { useGlobalState } from '../../composables/useGlobalState'
import { AgentBoardKey } from './context'
import NodeConfigSection from './NodeConfigSection.vue'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected

const { lastError, providers, availableTools, nodeConfigDockWidth: configDockWidth } = useGlobalState()

const CONFIG_DOCK_WIDTH_KEY = 'agentpark.nodeConfigDockWidth'
const CONFIG_DOCK_DEFAULT_WIDTH = 360
const CONFIG_DOCK_MIN_WIDTH = 320
const resizeStart = ref<{ clientX: number; width: number } | null>(null)

function maxDockWidth() {
  return Math.max(CONFIG_DOCK_MIN_WIDTH, Math.floor(window.innerWidth * 0.75))
}

function clampDockWidth(width: number) {
  return Math.max(CONFIG_DOCK_MIN_WIDTH, Math.min(maxDockWidth(), Math.round(width)))
}

function readStoredDockWidth() {
  try {
    const stored = Number(window.localStorage.getItem(CONFIG_DOCK_WIDTH_KEY))
    if (Number.isFinite(stored) && stored > 0) return clampDockWidth(stored)
  } catch {
    // Local storage is optional; the default width remains usable without it.
  }
  return CONFIG_DOCK_DEFAULT_WIDTH
}

configDockWidth.value = readStoredDockWidth()

function persistDockWidth() {
  try {
    window.localStorage.setItem(CONFIG_DOCK_WIDTH_KEY, String(configDockWidth.value))
  } catch {
    // Ignore browser storage restrictions.
  }
}

function onResizeMove(event: PointerEvent) {
  const session = resizeStart.value
  if (!session) return
  configDockWidth.value = clampDockWidth(session.width + event.clientX - session.clientX)
  event.preventDefault()
}

function stopResize() {
  if (!resizeStart.value) return
  resizeStart.value = null
  persistDockWidth()
  window.removeEventListener('pointermove', onResizeMove)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('blur', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

function startResize(event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  event.stopPropagation()
  resizeStart.value = { clientX: event.clientX, width: configDockWidth.value }
  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', onResizeMove)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('blur', stopResize)
}

onBeforeUnmount(stopResize)

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

function showEditorError(message: string) {
  lastError.value = String(message || '').trim() || null
}
</script>

<template>
  <aside
    v-if="selectedNode"
    class="node-config-dock"
    data-board-occlusion="left"
    :style="{ width: `${configDockWidth}px` }"
  >
    <div class="config-dock-head">
      <div class="config-title-wrap">
        <div class="config-title">{{ selectedNode.name }}</div>
        <div class="config-sub">{{ selectedNode.typeId }} / {{ selectedNode.id }}</div>
      </div>
    </div>

    <NodeConfigSection
      class="config-section-host"
      :node="selectedNode"
      :config="selectedConfig"
      :providers="providers"
      :available-tools="availableTools"
      @error="showEditorError"
    />
    <div class="config-dock-resize-handle" title="拖动调整 Config 面板宽度" @pointerdown="startResize"></div>
  </aside>
</template>

<style scoped>
.node-config-dock {
  position: absolute;
  inset: 0 auto 0 0;
  z-index: 80;
  min-width: 320px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
  padding: 14px;
  border-right: 1px solid var(--theme-panel-node-side-editor-border-color, rgba(148, 163, 184, 0.24));
  background-color: var(--theme-panel-node-side-editor-background-color, rgba(2, 6, 23, 0.96));
  background-image: var(--theme-panel-node-side-editor-background-image, none);
  background-size: var(--theme-panel-node-side-editor-background-size, cover);
  background-position: var(--theme-panel-node-side-editor-background-position, center);
  background-repeat: var(--theme-panel-node-side-editor-background-repeat, no-repeat);
  background-blend-mode: var(--theme-panel-node-side-editor-background-blend-mode, normal);
}

.config-dock-resize-handle {
  position: absolute;
  z-index: 20;
  top: 0;
  right: -6px;
  bottom: 0;
  width: 12px;
  cursor: ew-resize;
}

.config-dock-resize-handle::before {
  content: '';
  position: absolute;
  top: 10px;
  right: 5px;
  bottom: 10px;
  width: 2px;
  background: transparent;
  transition: background 0.12s ease;
}

.config-dock-resize-handle:hover::before,
.config-dock-resize-handle:active::before {
  background: var(--accent-blue, #38bdf8);
}

.config-dock-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.config-title-wrap {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.config-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 16px;
  font-weight: 700;
  color: var(--theme-panel-node-side-editor-text-primary, #f8fafc);
}

.config-sub {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--theme-panel-node-side-editor-text-secondary, rgba(148, 163, 184, 0.84));
}

.config-section-host {
  flex: 1 1 auto;
  min-height: 0;
}
</style>
