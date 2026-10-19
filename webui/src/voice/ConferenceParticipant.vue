<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useNodeVoiceCall } from '../composables/useNodeVoiceCall'
import type { ConferenceAudio } from './ConferenceAudio'
import { useVoiceDesktopTools } from './useVoiceDesktopTools'
import { useWorkspaceVoice } from './workspaceVoice'

const props = defineProps<{ participantId: number; nodeId: string; graphId: string; audio: ConferenceAudio; running: boolean; canRetry: boolean }>()
const emit = defineEmits<{ state: [id: number, active: boolean, connected: boolean]; record: [id: number, pending: boolean]; retry: [] }>()
const quiet = ref(false)
const workspace = useWorkspaceVoice()
const voice = useNodeVoiceCall({ readComposer: target => workspace.composers.read(target),
  annotateScreen: drawing => desktop.draw(drawing),
  captureScreen: (id, display) => desktop.capture(id, display),
  editComposer: (target, edit) => workspace.composers.edit(target, edit), media: {
  acquire: async () => props.audio.input(props.nodeId),
  receive: stream => { props.audio.receive(props.nodeId, stream); props.audio.mutePlayback(props.nodeId, quiet.value) },
  release: () => props.audio.leave(props.nodeId),
} })
const desktop = useVoiceDesktopTools(voice.desktopSession, voice.connected)
function togglePlayback() { quiet.value = !quiet.value; props.audio.mutePlayback(props.nodeId, quiet.value) }
watch([voice.active, voice.connected], () => emit('state', props.participantId, voice.active.value, voice.connected.value))
watch([voice.recordSaving, voice.recordError], () => emit('record', props.participantId, voice.recordSaving.value || !!voice.recordError.value), { flush: 'sync' })
watch(() => props.running, running => { if (!running) voice.hangup() })
onMounted(async () => {
  if (props.running) await voice.start(props.nodeId, props.graphId)
  emit('state', props.participantId, voice.active.value, voice.connected.value)
})
</script>

<template>
  <article class="conference-participant">
    <header><strong>{{ nodeId }}</strong><span>{{ voice.stage.value || '等待连接' }}</span></header>
    <p v-if="voice.error.value" role="alert">{{ voice.error.value }}</p>
    <p v-if="voice.contextStatus.value" role="status">{{ voice.contextStatus.value }}</p>
    <p v-if="voice.feedbackStatus.value" role="status">{{ voice.feedbackStatus.value }}</p>
    <small v-if="voice.recordSaving.value">正在保存语音记录…</small>
    <p v-if="voice.recordError.value" role="alert">{{ voice.recordError.value }}
      <button type="button" :disabled="voice.recordSaving.value" @click="voice.saveRecord">重试保存</button>
    </p>
    <p v-if="voice.userCaption.value" class="caption">听到：{{ voice.userCaption.value }}</p>
    <p v-if="voice.assistantCaption.value" class="caption">{{ voice.assistantCaption.value }}</p>
    <small v-if="voice.taskStatus.value">{{ voice.taskStatus.value }}</small>
    <p v-if="desktop.error.value" role="alert">{{ desktop.error.value }}</p>
    <button v-if="voice.connected.value && desktop.drawn.value" type="button" @click="desktop.clear">清除标注</button>
    <div v-if="voice.active.value" class="actions">
      <button type="button" :aria-pressed="quiet" @click="togglePlayback">{{ quiet ? '恢复收听' : '不收听此节点' }}</button>
      <button type="button" @click="voice.hangup">挂断 {{ nodeId }}</button>
    </div>
    <div v-else-if="canRetry" class="actions">
      <button type="button" :disabled="voice.recordSaving.value || !!voice.recordError.value" @click="emit('retry')">重新呼叫 {{ nodeId }}</button>
      <small>设备连接恢复后可重新呼叫，其他节点继续通话。</small>
    </div>
  </article>
</template>

<style scoped>
.conference-participant { color: var(--voice-foreground); padding: 8px; border: 1px solid var(--voice-border); border-radius: 8px; min-width: 0; }
header, .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
header span, small { color: var(--voice-muted); font-size: 12px; }
p { margin: 6px 0; overflow-wrap: anywhere; font-size: 13px; }
p[role=alert] { color: var(--voice-error); }
.caption { max-height: 5em; overflow: auto; }
.actions { margin-top: 6px; }
button { color: var(--voice-foreground); background: var(--voice-background); border: 1px solid var(--voice-border); border-radius: 6px; padding: 6px 9px; cursor: pointer; }
</style>
