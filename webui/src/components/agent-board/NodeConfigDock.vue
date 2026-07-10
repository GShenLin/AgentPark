<script setup lang="ts">
import { computed, inject } from 'vue'
import { useGlobalState } from '../../composables/useGlobalState'
import { AgentBoardKey } from './context'
import NodeConfigSection from './NodeConfigSection.vue'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected

const { lastError, providers, availableTools } = useGlobalState()

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
  <aside v-if="selectedNode" class="node-config-dock" data-board-occlusion="left">
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
  </aside>
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
