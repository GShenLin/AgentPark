import { computed, onBeforeUnmount, ref } from 'vue'
import { getActiveApiBase } from '../api'
import { createVoiceCall, getVoiceTask, submitVoiceTask, voiceRequest, type VoiceTarget } from '../voiceApi'
import { delegationResult, parseVoiceEvent, type VoiceEvent } from './codexVoiceProtocol'

type Line = { role: 'user' | 'assistant'; text: string }
export type VoiceMedia = {
  acquire: () => Promise<MediaStream>
  receive: (stream: MediaStream) => void
  release: () => void
}
type Call = {
  target: VoiceTarget; controller: AbortController; pc: RTCPeerConnection
  audio: HTMLAudioElement; stream?: MediaStream; dc?: RTCDataChannel; session?: string
  timer?: ReturnType<typeof setTimeout>; seen: Map<string, string>; partial: Partial<Record<Line['role'], string>>
}

export function useNodeVoiceCall(options: { media?: VoiceMedia; conference?: boolean } = {}) {
  const active = ref(false), connected = ref(false), muted = ref(false)
  const stage = ref(''), error = ref(''), taskStatus = ref('')
  const lines = ref<Line[]>([])
  const userCaption = ref(''), assistantCaption = ref('')
  const supported = computed(() => typeof RTCPeerConnection !== 'undefined' && !!navigator.mediaDevices?.getUserMedia)
  let call: Call | undefined

  function isCurrent(candidate: Call) { return call === candidate && !candidate.controller.signal.aborted }

  function send(candidate: Call, event: object) {
    if (!isCurrent(candidate) || candidate.dc?.readyState !== 'open') throw new Error('语音数据通道已断开。')
    candidate.dc.send(JSON.stringify(event))
  }

  function stop(diagnostic: 'ended' | 'error' = 'ended') {
    const previous = call
    call = undefined; active.value = false; connected.value = false; muted.value = false
    taskStatus.value = ''
    if (!previous) return
    clearTimeout(previous.timer)
    try {
      if (previous.dc?.readyState === 'open') previous.dc.send(JSON.stringify({ type: 'session.close' }))
    } catch (e) {
      error.value += `${error.value ? '\n' : ''}发送挂断通知失败：${e instanceof Error ? e.message : String(e)}`
    }
    previous.controller.abort()
    previous.stream?.getTracks().forEach(track => track.stop())
    previous.audio.pause(); previous.audio.srcObject = null
    previous.dc?.close(); previous.pc.close()
    options.media?.release()
    if (previous.session) {
      const suffix = `/${encodeURIComponent(previous.session)}`
      const detail = error.value.slice(0, 1500), lastStage = stage.value
      void (async () => {
        try {
          await voiceRequest(previous.target, `${suffix}/events`, {
            method: 'POST', body: JSON.stringify({ event: diagnostic, stage: lastStage, detail }),
          })
        } finally { await voiceRequest(previous.target, suffix, { method: 'DELETE' }) }
      })().catch((e: Error) => { if (!call) error.value += `${error.value ? '\n' : ''}保存通话状态失败：${e.message}` })
    }
  }

  function fail(candidate: Call, message: string) {
    if (!isCurrent(candidate)) return
    const wasConnected = connected.value
    error.value = message
    stop('error')
    stage.value = wasConnected ? '通话已中断' : '通话未接通'
  }

  function hangup() { stop(); stage.value = '通话已结束' }

  function toggleMute() {
    if (!call?.stream) return
    muted.value = !muted.value
    call.stream.getAudioTracks().forEach(track => { track.enabled = !muted.value })
  }

  async function delegate(candidate: Call, event: Extract<VoiceEvent, { kind: 'delegation' }>) {
    const previous = candidate.seen.get(event.id)
    if (previous !== undefined) {
      if (previous !== event.text) throw new Error('重复的语音任务编号包含不同内容。')
      return
    }
    candidate.seen.set(event.id, event.text)
    if (!candidate.session) throw new Error('语音任务没有绑定节点会话。')
    taskStatus.value = '正在提交节点任务…'
    try {
      const id = await submitVoiceTask(candidate.target, candidate.session, event.id, event.text, candidate.controller.signal)
      while (isCurrent(candidate)) {
        const result = await getVoiceTask(candidate.target, candidate.session, id, candidate.controller.signal)
        if (!isCurrent(candidate)) return
        if (result.status === 'queued' || result.status === 'running') {
          taskStatus.value = result.status === 'queued' ? '节点任务已排队，通话保持中' : '节点正在执行，通话保持中'
          await new Promise(resolve => setTimeout(resolve, 800))
          continue
        }
        taskStatus.value = result.status === 'completed' ? '节点任务已完成' : '节点任务未完成'
        const output = `节点任务状态：${result.status}。结果：\n${result.text}`
        for (const message of delegationResult(event.id, output)) send(candidate, message)
        return
      }
    } catch (e) {
      if (!isCurrent(candidate)) return
      const message = e instanceof Error ? e.message : String(e)
      error.value = `节点任务反馈失败：${message}`
      for (const item of delegationResult(event.id, `节点任务错误：${message}。未确认执行成功。`)) send(candidate, item)
    }
  }

  function receive(candidate: Call, raw: string) {
    if (!isCurrent(candidate)) return
    try {
      const event = parseVoiceEvent(raw)
      if (event.kind === 'error') { fail(candidate, event.text); return }
      if (event.kind === 'closed') { hangup(); return }
      if (event.kind === 'ready') {
        clearTimeout(candidate.timer); connected.value = true; stage.value = '通话中'
      } else if (event.kind === 'transcript') {
        const caption = event.role === 'user' ? userCaption : assistantCaption
        if (event.done) {
          caption.value = event.text
          lines.value = [...lines.value.slice(-29), { role: event.role, text: event.text }]
          candidate.partial[event.role] = ''
        } else {
          candidate.partial[event.role] = (candidate.partial[event.role] || '') + event.text
          caption.value = candidate.partial[event.role] || ''
        }
      } else if (event.kind === 'delegation') {
        void delegate(candidate, event).catch(e => fail(candidate, e instanceof Error ? e.message : String(e)))
      }
    } catch (e) { fail(candidate, e instanceof Error ? e.message : String(e)) }
  }

  async function start(node: string, graph: string) {
    if (active.value) return
    error.value = ''; stage.value = '正在请求麦克风权限…'; lines.value = []
    userCaption.value = ''; assistantCaption.value = ''; taskStatus.value = ''
    if (!supported.value) {
      error.value = '当前页面无法使用麦克风。请通过 localhost 或 HTTPS 打开，并允许浏览器访问麦克风。'
      return
    }
    const candidate: Call = {
      target: { base: getActiveApiBase(), node, graph }, controller: new AbortController(),
      pc: new RTCPeerConnection(), audio: new Audio(), seen: new Map(), partial: {},
    }
    call = candidate; active.value = true
    candidate.audio.autoplay = true
    try {
      const stream = await (options.media ? options.media.acquire() : navigator.mediaDevices.getUserMedia({ audio: {
        echoCancellation: true, noiseSuppression: true, autoGainControl: true,
      } }))
      if (!isCurrent(candidate)) { stream.getTracks().forEach(track => track.stop()); return }
      candidate.stream = stream
      stream.getAudioTracks().forEach(track => {
        candidate.pc.addTrack(track, stream)
        track.onended = () => fail(candidate, '麦克风已断开或访问权限已撤回。')
      })
      candidate.pc.ontrack = event => {
        if (!isCurrent(candidate)) return
        if (options.media) {
          try {
            const incoming = new MediaStream([event.track])
            // Chromium must start the remote media renderer before Web Audio
            // receives samples. The conference mixer owns audible playback.
            candidate.audio.muted = true
            candidate.audio.srcObject = incoming
            void candidate.audio.play().catch(e => fail(candidate, `无法接收通话声音：${e.message}`))
            options.media.receive(incoming)
          }
          catch (e) { fail(candidate, e instanceof Error ? e.message : String(e)) }
          return
        }
        candidate.audio.srcObject = new MediaStream([event.track])
        void candidate.audio.play().catch(e => fail(candidate, `无法播放通话声音：${e.message}`))
      }
      candidate.pc.onconnectionstatechange = () => {
        if (candidate.pc.connectionState === 'failed') fail(candidate, 'WebRTC 音频连接失败，请检查网络连接。')
        else if (candidate.pc.connectionState === 'disconnected' && isCurrent(candidate)) stage.value = '音频连接暂时中断…'
        else if (candidate.pc.connectionState === 'connected' && connected.value && isCurrent(candidate)) stage.value = '通话中'
      }
      const dc = candidate.pc.createDataChannel('oai-events'); candidate.dc = dc
      dc.onopen = () => {
        if (!isCurrent(candidate)) return
        stage.value = '音频通道已连接，等待语音服务接受会话…'
      }
      dc.onmessage = event => receive(candidate, event.data)
      dc.onerror = () => fail(candidate, '语音数据通道发生错误。')
      dc.onclose = () => fail(candidate, '语音服务已关闭连接。')
      stage.value = '正在建立语音连接…'
      await candidate.pc.setLocalDescription(await candidate.pc.createOffer())
      if (!isCurrent(candidate)) return
      const answer = await createVoiceCall(candidate.target, candidate.pc.localDescription!.sdp, candidate.controller.signal, options.conference)
      if (!isCurrent(candidate)) {
        await voiceRequest(candidate.target, `/${encodeURIComponent(answer.session_id)}`, { method: 'DELETE' })
        return
      }
      candidate.session = answer.session_id
      stage.value = '通话已创建，正在连接音频…'
      candidate.timer = setTimeout(() => fail(candidate, '等待语音会话启动超时。服务端尚未确认通话可用。'), 25_000)
      await candidate.pc.setRemoteDescription({ type: 'answer', sdp: answer.sdp })
    } catch (e) { fail(candidate, e instanceof Error ? e.message : String(e)) }
  }

  onBeforeUnmount(() => stop())
  return { active, connected, muted, stage, error, taskStatus, lines, userCaption, assistantCaption,
    supported, start, hangup, toggleMute }
}
