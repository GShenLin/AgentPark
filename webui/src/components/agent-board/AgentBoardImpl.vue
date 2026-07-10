<script setup lang="ts">
import { inject, provide } from 'vue'
import { AgentBoardKey } from './context'
import { useAgentBoard } from './useAgentBoard'
import BoardCanvas from './BoardCanvas.vue'
import NodeInputDock from './NodeInputDock.vue'

const injected = inject(AgentBoardKey, null)
const ctx = injected ?? useAgentBoard()
provide(AgentBoardKey, ctx)
</script>

<template>
  <div class="agent-board-wrapper">
    <BoardCanvas />
    <NodeInputDock />
  </div>
</template>

<style scoped>
.agent-board-wrapper {
  flex: 1;
  min-height: 0;
  display: flex;
  position: relative;
  overflow: hidden;
}
</style>
