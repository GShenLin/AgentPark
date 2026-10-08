import { computed, ref, shallowRef } from 'vue'
import { ConferenceAudio } from './ConferenceAudio'

export type VoiceParticipant = { id: number; node: string; active: boolean; connected: boolean }

// Explicit lifetime: the workspace owns rooms, never a chat panel's lifecycle.
export function createVoiceRoom() {
  const audio = shallowRef<ConferenceAudio | null>(null)
  const participants = ref<VoiceParticipant[]>([])
  const active = ref(false), opened = ref(false), muted = ref(false), error = ref('')
  const connected = computed(() => participants.value.filter(p => p.connected).length)
  let generation = 0, sequence = 0

  function stop() {
    generation++; active.value = false; muted.value = false
    const previous = audio.value
    if (previous) void previous.close().catch(cause => { error.value = `关闭通话声音失败：${String(cause)}` })
  }

  function add(nodes: string[]) {
    if (!active.value || !opened.value) return
    for (const node of new Set(nodes)) {
      if (participants.value.some(p => p.node === node && p.active)) continue
      participants.value = participants.value.filter(p => p.node !== node)
      participants.value.push({ id: ++sequence, node, active: true, connected: false })
    }
  }

  async function start(node: string) {
    if (active.value) return
    if (typeof AudioContext === 'undefined' || typeof RTCPeerConnection === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      error.value = '当前页面无法使用实时通话。请通过 HTTPS 或 localhost 打开，并允许麦克风访问。'; return
    }
    error.value = ''; opened.value = false; muted.value = false; participants.value = []
    const epoch = ++generation
    active.value = true
    try {
      const mixer = new ConferenceAudio(); audio.value = mixer
      await mixer.open(() => { if (epoch === generation) { error.value = '麦克风已断开或权限已撤回。'; stop() } })
      if (epoch !== generation) return
      mixer.muteMicrophone(muted.value)
      opened.value = true; add([node])
    } catch (cause) {
      if (epoch !== generation) return
      error.value = cause instanceof Error ? cause.message : String(cause); stop()
    }
  }

  function stateChanged(id: number, running: boolean, ready: boolean) {
    if (!active.value) return
    const participant = participants.value.find(p => p.id === id)
    if (!participant) return
    participant.active = running; participant.connected = ready
    if (participants.value.every(p => !p.active)) stop()
  }
  function toggleMute() { muted.value = !muted.value; audio.value?.muteMicrophone(muted.value) }
  function leave(node: string) {
    const participant = participants.value.find(p => p.node === node && p.active)
    if (participant) stateChanged(participant.id, false, false)
    else if (!opened.value) stop()
  }
  return { audio, participants, active, opened, muted, error, connected, start, stop, add, leave, stateChanged, toggleMute }
}
