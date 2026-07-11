<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useGlobalState } from '../../composables/useGlobalState'
import { AgentBoardKey } from './context'
import NodeConfigSection from './NodeConfigSection.vue'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected

const { lastError, providers, availableTools } = useGlobalState()
const isFullscreen = ref(false)

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

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
}

watch(
  () => ctx.selectedNodeId.value,
  () => {
    isFullscreen.value = false
  },
)
</script>

<template>
  <Teleport to="body" :disabled="!isFullscreen">
    <aside
      v-if="selectedNode"
      class="node-config-dock"
      :class="{ fullscreen: isFullscreen }"
      data-board-occlusion="left"
    >
      <div class="config-dock-head">
        <div class="config-title-wrap">
          <div class="config-title">{{ selectedNode.name }}</div>
          <div class="config-sub">{{ selectedNode.typeId }} / {{ selectedNode.id }}</div>
        </div>
        <button
          type="button"
          class="fullscreen-btn"
          :aria-label="isFullscreen ? '退出全屏' : '全屏查看'"
          :title="isFullscreen ? '退出全屏' : '全屏查看'"
          @click="toggleFullscreen"
        >
          <svg v-if="!isFullscreen" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M5 9V5h4M15 5h4v4M19 15v4h-4M9 19H5v-4" />
          </svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M9 5v4H5M19 9h-4V5M15 19v-4h4M5 15h4v4" />
          </svg>
        </button>
      </div>

      <NodeConfigSection
        class="config-section-host"
        :node="selectedNode"
        :config="selectedConfig"
        :providers="providers"
        :available-tools="availableTools"
        @error="showEditorError"
      />
    </aside>
  </Teleport>
</template>

<style scoped>
.node-config-dock {
  position: absolute;
  inset: 0 auto 0 0;
  z-index: 80;
  width: 360px;
  min-width: 320px;
  max-width: 420px;
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

.node-config-dock.fullscreen {
  position: fixed;
  inset: 60px 10px 10px;
  z-index: 2100;
  width: auto;
  min-width: 0;
  max-width: none;
  border: 1px solid var(--theme-panel-node-side-editor-border-color, rgba(148, 163, 184, 0.24));
  border-radius: 6px;
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

.fullscreen-btn {
  flex: 0 0 32px;
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 1px solid var(--theme-panel-node-side-editor-border-color, rgba(148, 163, 184, 0.24));
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.72);
  color: var(--theme-panel-node-side-editor-text-primary, #f8fafc);
  cursor: pointer;
}

.fullscreen-btn:hover {
  background: rgba(51, 65, 85, 0.86);
}

.fullscreen-btn:focus-visible {
  outline: 2px solid var(--theme-panel-topbar-button-active-text, #60a5fa);
  outline-offset: 2px;
}

.fullscreen-btn svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.config-section-host {
  flex: 1 1 auto;
  min-height: 0;
}
</style>
