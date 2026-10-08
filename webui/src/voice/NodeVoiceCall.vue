<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { listMobileNodes, type MobileNode } from '../api'
import { useWorkspaceVoice, type WorkspaceVoiceSession } from './workspaceVoice'
import ConferenceParticipant from './ConferenceParticipant.vue'
import { SCREEN_FPS_MIN, SCREEN_FPS_MAX, useScreenShare } from './useScreenShare'

const props = defineProps<{ session: WorkspaceVoiceSession }>()
const emit = defineEmits<{ dismiss: [] }>()
const workspace = useWorkspaceVoice()
const room = props.session.room
const graphId = props.session.graphId
const screen = useScreenShare()
const frameRates = Array.from({ length: SCREEN_FPS_MAX - SCREEN_FPS_MIN + 1 }, (_, i) => i + SCREEN_FPS_MIN)
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

async function changeFrameRate(event: Event) {
  const select = event.target as HTMLSelectElement
  await screen.setFrameRate(Number(select.value))
  select.value = String(screen.frameRate.value)
}

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
watch(room.active, value => { if (!value) { screen.stop(); requestVersion++; picking.value = false; loading.value = false } }, { flush: 'sync' })
</script>

<template>
  <section class="node-voice-call" aria-label="节点语音通话">
    <div v-if="room.active.value" class="voice-toolbar">
      <strong>{{ room.opened.value ? `通话中 · ${room.connected.value} 个节点已接通` : '正在打开麦克风…' }}</strong>
      <button type="button" :aria-pressed="room.muted.value" @click="room.toggleMute">{{ room.muted.value ? '打开麦克风' : '静音麦克风' }}</button>
      <button type="button" :aria-pressed="!!screen.stream.value" :disabled="!screen.stream.value && (!screen.available.value || screen.pending.value)"
        :title="screen.available.value ? '选择窗口、标签页或整个屏幕，画面直接发送给通话模型' : '接通 OpenAI Realtime 或火山视觉语音节点后可共享屏幕'"
        @click="screen.stream.value ? screen.stop() : screen.start()">{{ screen.stream.value ? '停止共享' : screen.pending.value ? '正在选择屏幕…' : '共享屏幕' }}</button>
      <button type="button" @click="room.stop">全部挂断</button>
    </div>
    <div v-else class="voice-toolbar"><strong>通话已结束</strong><button type="button" :disabled="pendingRecords.size > 0" @click="emit('dismiss')">关闭</button></div>
    <p v-if="room.error.value" role="alert">{{ room.error.value }}</p>
    <p v-if="screen.error.value" role="alert">{{ screen.error.value }}</p>
    <div v-if="screen.stream.value" class="screen-preview">
      <video :srcObject="screen.stream.value" autoplay muted playsinline aria-label="共享画面预览" />
      <div><strong>正在共享：{{ screen.label.value }}</strong><p>发送给：{{ screen.names.value }}</p>
        <label>共享帧率
          <select :value="screen.frameRate.value" :disabled="screen.changingRate.value" aria-label="共享帧率"
            @change="changeFrameRate">
            <option v-for="fps in frameRates" :key="fps" :value="fps">{{ fps }} 帧/秒</option>
          </select>
        </label>
        <p v-for="rate in screen.rates.value" :key="rate.id"><small>{{ rate.name }} · 实际发送 {{ rate.fps.toFixed(1) }} 帧/秒（近 2 秒）</small></p>
        <p v-if="screen.hasRtc.value"><small>火山 RTC 上传视频流；模型抽帧上限 10 帧/秒，上传帧率不等于模型处理帧率。</small></p>
        <small>{{ screen.sent.value || screen.rates.value.some(rate => rate.fps > 0) ? '画面持续更新 · 语音可继续交流' : '正在准备首帧画面…' }}</small></div>
    </div>
    <div v-if="room.audio.value && room.opened.value" class="voice-participants">
      <ConferenceParticipant v-for="participant in room.participants.value" :key="participant.id" :participant-id="participant.id"
        :node-id="participant.node" :graph-id="graphId" :audio="room.audio.value" :running="room.active.value && participant.active" :screen="screen" @state="room.stateChanged"
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
.screen-preview { display: flex; gap: 10px; align-items: center; margin: 8px 0; padding: 8px; border: 1px solid var(--voice-border); border-radius: 8px; }
.screen-preview video { width: 160px; max-width: 40%; max-height: 100px; object-fit: contain; background: #111; }
.screen-preview div { min-width: 0; overflow-wrap: anywhere; }
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
