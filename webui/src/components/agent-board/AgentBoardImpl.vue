<script setup lang="ts">
import { inject, provide } from 'vue'
import { AgentBoardKey } from './context'
import { useAgentBoard } from './useAgentBoard'
import BoardCanvas from './BoardCanvas.vue'
import GroupBoardPanel from '../../groups/GroupBoardPanel.vue'

const injected = inject(AgentBoardKey, null)
const ctx = injected ?? useAgentBoard()
provide(AgentBoardKey, ctx)
</script>

<template>
  <div class="agent-board-wrapper">
    <BoardCanvas />
    <GroupBoardPanel :group="ctx.groups.active.value" @close="ctx.groups.activeId.value = null" @updated="ctx.groups.refresh()" :graph-id="ctx.currentGraphId.value || 'default'" :node-configs="ctx.nodeConfigs.value" />
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
