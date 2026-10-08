<script setup lang="ts">
import { computed } from 'vue'
import { useWorkspaceVoice } from './workspaceVoice'

const props = defineProps<{ graphId: string; nodeId: string; statusOnly?: boolean; disabled?: boolean }>()
const voice = useWorkspaceVoice()
const state = computed(() => voice.status(props.graphId, props.nodeId))
function click() {
  if (state.value) voice.hangup(props.graphId, props.nodeId)
  else voice.start(props.graphId, props.nodeId)
}
</script>

<template>
  <button v-if="!statusOnly || state" type="button" class="voice-call-button" :class="{ 'in-call': state }"
    :disabled="!state && disabled" :title="state ? '点击挂断此节点的通话' : '开始语音通话'"
    :aria-label="state ? `挂断 ${nodeId} 的通话` : `呼叫 ${nodeId}`" @pointerdown.stop @click.stop="click">
    {{ state === 'connected' ? '通话中' : state === 'connecting' ? '连接中' : '语音通话' }}
  </button>
</template>

<style scoped>
.voice-call-button { color: var(--text-primary); background: var(--bg-primary); border: 1px solid var(--border-medium); border-radius: 8px; padding: 6px 10px; cursor: pointer; flex-shrink: 0; }
.voice-call-button.in-call { color: var(--accent-green, #16804a); border-color: currentColor; }
.voice-call-button:disabled { opacity: .5; cursor: default; }
</style>
