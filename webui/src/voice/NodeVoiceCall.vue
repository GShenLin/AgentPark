<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { listMobileNodes, type MobileNode } from '../api'
import { useVoiceRoom } from './useVoiceRoom'
import ConferenceParticipant from './ConferenceParticipant.vue'

const props = defineProps<{ nodeId: string; graphId: string }>()
const room = useVoiceRoom()
const picking = ref(false), loading = ref(false), pickerError = ref('')
const nodes = ref<MobileNode[]>([]), selected = ref<string[]>([])
const available = computed(() => nodes.value.filter(node => node.type_id === 'agent_node'
  && !room.participants.value.some(p => p.node === node.id && p.active)))
let requestVersion = 0

async function pick() {
  picking.value = !picking.value
  if (!picking.value) return
  const version = ++requestVersion
  loading.value = true; pickerError.value = ''; selected.value = []
  try {
    const result = await listMobileNodes('local', props.graphId)
    if (version === requestVersion) nodes.value = result
  } catch (cause) {
    if (version === requestVersion) pickerError.value = cause instanceof Error ? cause.message : String(cause)
  } finally { if (version === requestVersion) loading.value = false }
}
function join() {
  room.add(selected.value.filter(id => available.value.some(node => node.id === id)))
  selected.value = []; picking.value = false
}
watch(room.active, value => { if (!value) { requestVersion++; picking.value = false; loading.value = false } })
watch(() => [props.nodeId, props.graphId], () => room.stop())
defineExpose({ start: () => room.start(props.nodeId), active: room.active })
</script>

<template>
  <section v-if="room.active.value || room.opened.value || room.error.value" class="node-voice-call" aria-label="节点语音通话">
    <div v-if="room.active.value" class="voice-toolbar">
      <strong>{{ room.opened.value ? `通话中 · ${room.connected.value} 个节点已接通` : '正在打开麦克风…' }}</strong>
      <button type="button" :aria-pressed="room.muted.value" @click="room.toggleMute">{{ room.muted.value ? '打开麦克风' : '静音麦克风' }}</button>
      <button type="button" @click="room.stop">全部挂断</button>
    </div>
    <div v-else class="voice-toolbar"><strong>通话已结束</strong><button type="button" @click="room.opened.value = false; room.error.value = ''">关闭</button></div>
    <p v-if="room.error.value" role="alert">{{ room.error.value }}</p>
    <div v-if="room.audio.value && room.opened.value" class="voice-participants">
      <ConferenceParticipant v-for="participant in room.participants.value" :key="participant.id" :participant-id="participant.id"
        :node-id="participant.node" :graph-id="graphId" :audio="room.audio.value" :running="room.active.value" @state="room.stateChanged"
        @retry="room.add([participant.node])" />
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
.node-voice-call { flex: 0 0 auto; min-width: 0; width: 100%; box-sizing: border-box; font-size: 13px; padding: 10px; margin-bottom: 8px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--bg-primary); max-height: 38vh; overflow: auto; }
.voice-toolbar, .voice-choices { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.voice-toolbar { margin-bottom: 8px; }
.voice-participants { display: grid; gap: 8px; max-height: 25vh; overflow: auto; }
.voice-add { margin-top: 8px; min-width: 40px; font-size: 20px; }
.voice-picker { margin-top: 8px; padding: 10px; border: 1px solid var(--border-color); border-radius: 8px; }
.voice-choices { margin: 8px 0; max-height: 20vh; overflow: auto; }
label { display: flex; align-items: center; gap: 4px; }
.voice-hint { color: var(--text-secondary); }
p { margin: 6px 0; overflow-wrap: anywhere; }
p[role=alert] { color: var(--accent-red); }
button { color: var(--text-primary); background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: 8px; padding: 7px 10px; min-height: 34px; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
</style>
