<script setup lang="ts">
import { computed } from 'vue'
import NodeVoiceCall from './NodeVoiceCall.vue'
import { useWorkspaceVoice } from './workspaceVoice'

const voice = useWorkspaceVoice()
const activeNodes = computed(() => voice.sessions.flatMap(({ graphId, nodeId, room }) => !room.active.value ? []
  : room.opened.value ? room.participants.value.filter(p => p.active).map(p => ({ graphId, nodeId: p.node })) : [{ graphId, nodeId }]))
</script>

<template>
  <aside v-if="voice.sessions.length" class="workspace-voice" aria-label="持续语音通话">
    <header>
      <button type="button" :aria-expanded="voice.expanded.value" @click="voice.expanded.value = !voice.expanded.value">
        {{ activeNodes.length ? `语音通话 · ${activeNodes.map(p => p.nodeId).join('、')}` : '通话记录' }}
        · {{ voice.expanded.value ? '收起' : '展开' }}
      </button>
      <button v-if="activeNodes.length" type="button" @click="voice.stopAll">全部挂断</button>
    </header>
    <!-- Visibility must never control the lifetime of a call or screen capture. -->
    <div v-show="voice.expanded.value" class="workspace-voice-details">
      <NodeVoiceCall v-for="session in voice.sessions" :key="session.id" :session="session" @dismiss="voice.dismiss(session.id)" />
    </div>
  </aside>
</template>

<style scoped>
.workspace-voice { position: fixed; z-index: 1500; right: 16px; bottom: max(16px, env(safe-area-inset-bottom)); width: min(460px, calc(100vw - 24px)); max-height: 65dvh; border: 1px solid var(--border-medium); border-radius: 12px; background: var(--bg-primary); color: var(--text-primary); box-shadow: 0 4px 24px #0003; }
header { display: flex; align-items: center; gap: 8px; padding: 8px; }
header button { border: 1px solid var(--border-medium); border-radius: 8px; padding: 8px; color: inherit; background: inherit; cursor: pointer; }
header button:first-child { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.workspace-voice-details { max-height: 55dvh; overflow: auto; padding: 0 8px; }
@media (max-width: 760px) { .workspace-voice { right: 12px; top: max(60px, env(safe-area-inset-top)); bottom: auto; } }
</style>
