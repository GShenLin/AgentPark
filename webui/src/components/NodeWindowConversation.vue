<script setup lang="ts">
import type { GraphInfo, GraphProfile } from '../api'
import MemoryPanel from './MemoryPanel.vue'
import NodeInputDock from './agent-board/NodeInputDock.vue'
import NodeConfigDock from './agent-board/NodeConfigDock.vue'
import ActionButton from './ActionButton.vue'

defineProps<{
  graphs: GraphInfo[]
  graphProfiles: GraphProfile[]
  settingsOpen: boolean
}>()
defineEmits<{ closeSettings: [] }>()
</script>

<template>
  <section class="node-window-conversation" data-node-window-interactive
    @pointerdown.stop @click.stop @contextmenu.stop @dragover.stop @drop.stop>
    <div class="node-window-memory chat-appearance" aria-label="节点回复">
      <MemoryPanel :initial-graphs="graphs" :initial-graph-profiles="graphProfiles" hide-header :active="!settingsOpen" />
    </div>
    <NodeInputDock :window-paste="!settingsOpen" />
    <section v-if="settingsOpen" class="node-window-settings" aria-label="节点设置">
      <div class="node-window-settings-toolbar"><ActionButton @click="$emit('closeSettings')">返回对话</ActionButton></div>
      <NodeConfigDock />
    </section>
  </section>
</template>

<style scoped>
.node-window-conversation { position: relative; display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: hidden; border-radius: 0 0 12px 12px; cursor: auto; user-select: text; touch-action: auto; }
.node-window-memory { flex: 1; min-height: 0; overflow: hidden; }
.node-window-memory > :deep(.panel) { height: 100%; border: 0; border-radius: 0; }
.node-window-conversation > :deep(.node-input-dock) { padding: 8px 12px 12px; }
.node-window-settings { position: absolute; inset: 0; z-index: 10; display: flex; flex-direction: column; background: var(--bg-primary); }
.node-window-settings-toolbar { flex: 0 0 auto; display: flex; justify-content: flex-end; padding: 6px 12px; }
.node-window-settings > :deep(.node-config-dock) { position: relative; inset: auto; flex: 1; min-height: 0; min-width: 0; width: 100% !important; border: 0; }
.node-window-settings :deep(.config-dock-resize-handle) { display: none; }
</style>
