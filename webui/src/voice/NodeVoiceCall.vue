<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { listMobileNodes, type MobileNode } from '../api'
import { useWorkspaceVoice, type WorkspaceVoiceSession } from './workspaceVoice'
import ConferenceParticipant from './ConferenceParticipant.vue'

const props = defineProps<{ session: WorkspaceVoiceSession }>()
const emit = defineEmits<{ dismiss: [] }>()
const workspace = useWorkspaceVoice()
const room = props.session.room
const graphId = props.session.graphId
const picking = ref(false), loading = ref(false), pickerError = ref('')
const nodes = ref<MobileNode[]>([]), selected = ref<string[]>([])
const pendingRecords = ref(new Set<number>())
function recordChanged(id: number, pending: boolean) {
  if (pending) pendingRecords.value.add(id)
  else pendingRecords.value.delete(id)
}
const available = computed(() => nodes.value.filter(node => node.type_id === 'agent_node'
  && !workspace.status(graphId, node.id)))
let requestVersion = 0


async function pick() {
  picking.value = !picking.value
  if (!picking.value) return
  const version = ++requestVersion
  loading.value = true; pickerError.value = ''; selected.value = []
  try {
    const result = await listMobileNodes('local', graphId)
    if (version === requestVersion) nodes.value = result
  } catch (cause) {
    if (version === requestVersion) pickerError.value = cause instanceof Error ? cause.message : String(cause)
  } finally { if (version === requestVersion) loading.value = false }
}
function join() {
  room.add(selected.value.filter(id => available.value.some(node => node.id === id)))
  selected.value = []; picking.value = false
}
watch(room.active, value => { if (!value) { requestVersion++; picking.value = false; loading.value = false } }, { flush: 'sync' })
</script>

<template>
  <section class="node-voice-call" aria-label="节点语音通话">
    <div v-if="room.active.value" class="voice-toolbar">
      <strong>{{ room.opened.value ? `通话中 · ${room.connected.value} 个节点已接通` : '正在打开麦克风…' }}</strong>
      <button type="button" :aria-pressed="room.muted.value" @click="room.toggleMute">{{ room.muted.value ? '打开麦克风' : '静音麦克风' }}</button>
      <button type="button" @click="room.stop">全部挂断</button>
    </div>
    <div v-else class="voice-toolbar"><strong>通话已结束</strong><button type="button" :disabled="pendingRecords.size > 0" @click="emit('dismiss')">关闭</button></div>
    <p v-if="room.error.value" role="alert">{{ room.error.value }}</p>
    <div v-if="room.audio.value && room.opened.value" class="voice-participants">
      <ConferenceParticipant v-for="participant in room.participants.value" :key="participant.id" :participant-id="participant.id"
        :node-id="participant.node" :graph-id="graphId" :audio="room.audio.value" :running="room.active.value && participant.active" @state="room.stateChanged"
        :can-retry="room.active.value && !workspace.status(graphId, participant.node)" @record="recordChanged"
        @retry="!workspace.status(graphId, participant.node) && room.add([participant.node])" />
    </div>
    <template v-if="room.active.value && room.opened.value">
      <button class="voice-add" type="button" aria-label="添加节点加入通话" title="添加节点加入通话" :aria-expanded="picking" @click="pick">＋</button>
      <div v-if="picking" class="voice-picker">
        <strong>添加节点加入通话</strong>
        <p class="voice-hint">从当前画板选择节点，加入后彼此能听见。</p>
        <p v-if="loading">正在加载节点…</p>
        <p v-else-if="pickerError" role="alert">{{ pickerError }}</p>
        <template v-else>
          <div class="voice-choices"><label v-for="node in available" :key="node.id"><input v-model="selected" type="checkbox" :value="node.id">{{ node.name || node.id }}</label></div>
          <p v-if="!available.length">没有其他可添加的节点。</p>
          <button type="button" :disabled="!selected.length" @click="join">加入通话（{{ selected.length }}）</button>
        </template>
      </div>
    </template>
  </section>
</template>

<style scoped>
.node-voice-call {
  --voice-background: var(--theme-panel-node-side-editor-input-background, var(--bg-primary));
  --voice-foreground: var(--theme-panel-node-side-editor-input-text, var(--text-primary));
  --voice-muted: var(--theme-panel-node-side-editor-muted-text, var(--text-secondary));
  --voice-border: var(--theme-panel-node-side-editor-input-border, var(--border-medium));
  --voice-error: var(--ui-danger-text, var(--accent-red));
  color: var(--voice-foreground);
  flex: 0 0 auto; min-width: 0; width: 100%; box-sizing: border-box; font-size: 13px; padding: 10px; margin-bottom: 8px; border: 1px solid var(--voice-border); border-radius: 12px; background: var(--voice-background); max-height: 38vh; overflow: auto; }
.voice-toolbar, .voice-choices { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.voice-toolbar { margin-bottom: 8px; }
.voice-participants { display: grid; gap: 8px; max-height: 25vh; overflow: auto; }
.voice-add { margin-top: 8px; min-width: 40px; font-size: 20px; }
.voice-picker { margin-top: 8px; padding: 10px; border: 1px solid var(--voice-border); border-radius: 8px; }
.voice-choices { margin: 8px 0; max-height: 20vh; overflow: auto; }
label { display: flex; align-items: center; gap: 4px; }
.voice-hint { color: var(--voice-muted); }
p { margin: 6px 0; overflow-wrap: anywhere; }
p[role=alert] { color: var(--voice-error); }
button { color: var(--voice-foreground); background: var(--voice-background); border: 1px solid var(--voice-border); border-radius: 8px; padding: 7px 10px; min-height: 34px; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
select { color: var(--voice-foreground); background: var(--voice-background); border: 1px solid var(--voice-border); border-radius: 6px; padding: 4px; }
</style>
