import { computed, onBeforeUnmount, ref } from 'vue'
import { getActiveApiBase } from '../api'
import { createVoiceCall, describeVoiceCall, getVoiceTask, publishVoiceTaskUpdate, submitVoiceTask, voiceRequest, type VoiceTarget } from '../voiceApi'
import type { VolcRtcConnection } from '../voice/VolcRtcConnection'
import { voiceProtocol, type VoiceEvent, type VoiceProtocolAdapter } from '../voice/voiceProtocol'
import { completeVoiceOffer } from '../voice/webrtcOffer'
import { VoiceTranscript, type VoiceFinish } from '../voice/voiceTranscript'

type Line = { role: 'user' | 'assistant'; text: string }
export type VoiceMedia = {
  acquire: () => Promise<MediaStream>
  receive: (stream: MediaStream) => void
  release: () => void
}
type Call = {
  protocol?: VoiceProtocolAdapter
  transcript: VoiceTranscript
  target: VoiceTarget; controller: AbortController; pc?: RTCPeerConnection; rtc?: VolcRtcConnection
  audio: HTMLAudioElement; stream?: MediaStream; dc?: RTCDataChannel; session?: string
  timer?: ReturnType<typeof setTimeout>; seen: Map<string, string>; partial: Partial<Record<Line['role'], string>>
  feedbackTimer?: ReturnType<typeof setInterval>
}

export function useNodeVoiceCall(options: { media?: VoiceMedia } = {}) {
  const active = ref(false), connected = ref(false), muted = ref(false)
  const screenSupported = ref(false)
  const screenTransport = ref<'frames' | 'rtc'>('frames')
  const stage = ref(''), error = ref(''), taskStatus = ref('')
  const lines = ref<Line[]>([])
  const userCaption = ref(''), assistantCaption = ref('')
  const recordSaving = ref(false), recordError = ref('')
  let pendingRecord: { target: VoiceTarget; session: string; payload: VoiceFinish } | undefined
  const supported = computed(() => typeof RTCPeerConnection !== 'undefined' && !!navigator.mediaDevices?.getUserMedia)
  let call: Call | undefined

  function isCurrent(candidate: Call) { return call === candidate && !candidate.controller.signal.aborted }

  function send(candidate: Call, event: object) {
    if (!isCurrent(candidate) || candidate.dc?.readyState !== 'open') throw new Error('语音数据通道已断开。')
    candidate.dc.send(JSON.stringify(event))
  }

  async function saveRecord() {
    const pending = pendingRecord
    if (!pending || recordSaving.value) return
    recordSaving.value = true; recordError.value = ''
    try {
      const saved = await voiceRequest(pending.target, `/${encodeURIComponent(pending.session)}/finish`, {
        method: 'POST', body: JSON.stringify(pending.payload),
      })
      if (saved?.ok !== true || typeof saved.record_id !== 'string') throw new Error('语音服务未确认记录已保存。')
      if (pendingRecord === pending) pendingRecord = undefined
    } catch (cause) {
      recordError.value = `语音记录尚未保存，请重试：${cause instanceof Error ? cause.message : String(cause)}`
    } finally { recordSaving.value = false }
  }

  function stop(diagnostic: 'ended' | 'error' = 'ended') {
    const previous = call
    call = undefined; active.value = false; connected.value = false; muted.value = false; screenSupported.value = false
    taskStatus.value = ''
    if (!previous) return
    clearTimeout(previous.timer)
    clearInterval(previous.feedbackTimer)
    if (previous.protocol?.resultDelivery === 'data-channel') previous.protocol.dialogue.close()
    try {
      if (previous.protocol?.resultDelivery === 'server' && previous.dc?.readyState === 'open') previous.dc.send(JSON.stringify({ type: 'session.close' }))
    } catch (e) {
      error.value += `${error.value ? '\n' : ''}发送挂断通知失败：${e instanceof Error ? e.message : String(e)}`
    }
    previous.controller.abort()
    previous.stream?.getTracks().forEach(track => track.stop())
    previous.audio.pause(); previous.audio.srcObject = null
    previous.dc?.close(); previous.pc?.close()
    void previous.rtc?.close().catch(cause => { error.value = `关闭火山通话失败：${String(cause)}` })
    options.media?.release()
    if (previous.session) {
      pendingRecord = { target: previous.target, session: previous.session, payload: previous.transcript.finish(diagnostic) }
      void saveRecord()
      const suffix = `/${encodeURIComponent(previous.session)}`
      const detail = error.value.slice(0, 1500), lastStage = stage.value
      void (async () => {
        await voiceRequest(previous.target, `${suffix}/events`, {
          method: 'POST', body: JSON.stringify({ event: diagnostic, stage: lastStage, detail }),
        })
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
      const protocol = candidate.protocol!
      let previousFeedback = ''
      while (isCurrent(candidate)) {
        const result = await (protocol.resultDelivery === 'server' ? publishVoiceTaskUpdate : getVoiceTask)(
          candidate.target, candidate.session, id, candidate.controller.signal)
        const feedback = JSON.stringify(result)
        if (isCurrent(candidate) && protocol.resultDelivery === 'data-channel' && feedback !== previousFeedback) {
          protocol.dialogue.taskUpdate(event.id, result)
          previousFeedback = feedback
        }
        if (!isCurrent(candidate)) return
        if (result.status === 'queued' || result.status === 'running') {
          taskStatus.value = result.status === 'queued' ? '节点任务已排队，通话保持中' : '节点正在执行，通话保持中'
          await new Promise(resolve => setTimeout(resolve, 800))
          continue
        }
        taskStatus.value = result.status === 'completed' ? '节点任务已完成' : '节点任务未完成'
        return
      }
    } catch (e) {
      if (!isCurrent(candidate)) return
      const message = e instanceof Error ? e.message : String(e)
      error.value = `节点任务反馈失败：${message}`
      const protocol = candidate.protocol!
      if (protocol.resultDelivery === 'data-channel') {
        protocol.dialogue.taskUpdate(event.id, { status: 'failed', text: `节点任务反馈错误：${message}。未确认执行成功。` })
      }
    }
  }

  function receive(candidate: Call, raw: string) {
    if (!isCurrent(candidate)) return
    try {
      if (!candidate.protocol?.parse) throw new Error('语音通话尚未协商数据通道协议。')
      receiveEvent(candidate, candidate.protocol.parse(raw))
    } catch (e) { fail(candidate, e instanceof Error ? e.message : String(e)) }
  }

  function receiveEvent(candidate: Call, event: VoiceEvent) {
    if (!isCurrent(candidate)) return
    try {
      if (event.kind === 'error') { fail(candidate, event.text); return }
      if (event.kind === 'closed') { hangup(); return }
      if (event.kind === 'task-status') { taskStatus.value = event.text; return }
      if (event.kind === 'interrupted') {
        candidate.transcript.interrupt(event.role)
        if (!event.role || event.role === 'user') { candidate.partial.user = ''; userCaption.value = '' }
        if (!event.role || event.role === 'assistant') { candidate.partial.assistant = ''; assistantCaption.value = '' }
        return
      }
      if (event.kind === 'ready') {
        clearTimeout(candidate.timer); connected.value = true; stage.value = '通话中'
        if (candidate.session) void voiceRequest(candidate.target, `/${encodeURIComponent(candidate.session)}/events`, {
          method: 'POST', body: JSON.stringify({ event: 'connected', stage: '通话中', detail: '' }),
        }).catch(cause => { if (isCurrent(candidate)) error.value = `保存连接状态失败：${String(cause)}` })
      } else if (event.kind === 'transcript') {
        candidate.transcript.add(event)
        const caption = event.role === 'user' ? userCaption : assistantCaption
        if (event.done) {
          caption.value = event.text
          lines.value = [...lines.value.slice(-29), { role: event.role, text: event.text }]
          candidate.partial[event.role] = ''
        } else {
          candidate.partial[event.role] = (event.replace ? '' : candidate.partial[event.role] || '') + event.text
          caption.value = candidate.partial[event.role] || ''
        }
      } else if (event.kind === 'delegation') {
        void delegate(candidate, event).catch(e => fail(candidate, e instanceof Error ? e.message : String(e)))
      }
    } catch (e) { fail(candidate, e instanceof Error ? e.message : String(e)) }
  }

  async function start(node: string, graph: string) {
    if (active.value) return
    if (pendingRecord) {
      await saveRecord()
      if (pendingRecord) return
    }
    error.value = ''; stage.value = '正在请求麦克风权限…'; lines.value = []
    userCaption.value = ''; assistantCaption.value = ''; taskStatus.value = ''
    if (!supported.value) {
      error.value = '当前页面无法使用麦克风。请通过 localhost 或 HTTPS 打开，并允许浏览器访问麦克风。'
      return
    }
    const candidate: Call = {
      transcript: new VoiceTranscript(),
      target: { base: getActiveApiBase(), node, graph }, controller: new AbortController(),
      audio: new Audio(), seen: new Map(), partial: {},
    }
    call = candidate; active.value = true
    candidate.audio.autoplay = true
    try {
      const stream = await (options.media ? options.media.acquire() : navigator.mediaDevices.getUserMedia({ audio: {
        echoCancellation: true, noiseSuppression: true, autoGainControl: true,
      } }))
      if (!isCurrent(candidate)) { stream.getTracks().forEach(track => track.stop()); return }
      candidate.stream = stream
      for (const track of stream.getAudioTracks()) track.onended = () => fail(candidate, '麦克风已断开或访问权限已撤回。')
      const receiveAudio = (incoming: MediaStream) => {
        if (!isCurrent(candidate)) return
        if (options.media) {
          try {
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
        candidate.audio.srcObject = incoming
        void candidate.audio.play().catch(e => fail(candidate, `无法播放通话声音：${e.message}`))
      }
      const transport = await describeVoiceCall(candidate.target, candidate.controller.signal)
      if (!isCurrent(candidate)) return
      stage.value = '正在建立语音连接…'
      candidate.timer = setTimeout(() => fail(candidate, '等待语音会话启动超时。服务端尚未确认通话可用。'), 60_000)
      if (transport === 'volcengine-rtc') {
        const { VolcRtcConnection } = await import('../voice/VolcRtcConnection')
        if (!isCurrent(candidate)) return
        const answer = await createVoiceCall(candidate.target, undefined, candidate.controller.signal)
        if (!isCurrent(candidate)) {
          await voiceRequest(candidate.target, `/${encodeURIComponent(answer.session_id)}`, { method: 'DELETE' }); return
        }
        candidate.session = answer.session_id
        if (answer.transport !== 'volcengine-rtc') throw new Error('语音供应商已改变，请重新拨号。')
        candidate.protocol = voiceProtocol(answer.protocol)
        screenTransport.value = 'rtc'; screenSupported.value = true
        candidate.rtc = new VolcRtcConnection(candidate.target, answer.session_id, answer, candidate.controller.signal, {
          event: event => receiveEvent(candidate, event), audio: receiveAudio, error: message => fail(candidate, message),
        })
        await candidate.rtc.connect(stream)
        return
      }
      screenTransport.value = 'frames'
      const pc = new RTCPeerConnection(); candidate.pc = pc
      stream.getAudioTracks().forEach(track => pc.addTrack(track, stream))
      pc.ontrack = event => receiveAudio(new MediaStream([event.track]))
      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed') fail(candidate, 'WebRTC 音频连接失败，请检查网络连接。')
        else if (pc.connectionState === 'disconnected' && isCurrent(candidate)) stage.value = '音频连接暂时中断…'
        else if (pc.connectionState === 'connected' && connected.value && isCurrent(candidate)) stage.value = '通话中'
      }
      const dc = pc.createDataChannel('oai-events'); candidate.dc = dc
      dc.onopen = () => {
        if (!isCurrent(candidate)) return
        stage.value = '音频通道已连接，等待语音服务接受会话…'
      }
      dc.onmessage = event => receive(candidate, event.data)
      dc.onerror = () => fail(candidate, '语音数据通道发生错误。')
      dc.onclose = () => fail(candidate, '语音服务已关闭连接。')
      stage.value = '正在建立语音连接…'
      const sdp = await completeVoiceOffer(pc, candidate.controller.signal)
      if (!isCurrent(candidate)) return
      const answer = await createVoiceCall(candidate.target, sdp, candidate.controller.signal)
      if (!isCurrent(candidate)) {
        await voiceRequest(candidate.target, `/${encodeURIComponent(answer.session_id)}`, { method: 'DELETE' })
        return
      }
      candidate.session = answer.session_id
      if (answer.transport !== 'webrtc') throw new Error('语音供应商已改变，请重新拨号。')
      candidate.protocol = voiceProtocol(answer.protocol, event => send(candidate, event))
      screenSupported.value = candidate.protocol.resultDelivery === 'data-channel'
      if (candidate.protocol.resultDelivery === 'data-channel') {
        candidate.feedbackTimer = setInterval(() => {
          if (!isCurrent(candidate) || candidate.protocol?.resultDelivery !== 'data-channel') return
          try { candidate.protocol.dialogue.flush() }
          catch (e) { fail(candidate, e instanceof Error ? e.message : String(e)) }
        }, 250)
      }
      stage.value = '通话已创建，正在连接音频…'
      await pc.setRemoteDescription({ type: 'answer', sdp: answer.sdp })
    } catch (e) { fail(candidate, e instanceof Error ? e.message : String(e)) }
  }

  onBeforeUnmount(() => stop())
  function screenFrame(url: string) {
    if (!call || !connected.value || call.protocol?.resultDelivery !== 'data-channel') return false
    if ((call.dc?.bufferedAmount || 0) > 256000) return false
    return call.protocol.dialogue.screenFrame(url)
  }
  function screenStopped() {
    if (call && connected.value && call.protocol?.resultDelivery === 'data-channel') call.protocol.dialogue.screenStopped()
  }
  function screenMessageLimit() {
    const limit = call?.pc?.sctp?.maxMessageSize
    return limit && Number.isFinite(limit) ? Math.min(limit, 512000) : 64000
  }
  async function screenStream(stream: MediaStream | null, fps: number) {
    if (!call?.rtc || !connected.value) {
      if (stream) throw new Error('火山语音尚未接通。')
      return
    }
    await call.rtc.screen(stream, fps)
  }
  function screenFps() { return call?.rtc?.screenFps() || 0 }
  return { active, connected, muted, stage, error, taskStatus, lines, userCaption, assistantCaption,
    supported, start, hangup, toggleMute, recordSaving, recordError, saveRecord,
    screenSupported, screenFrame, screenStopped, screenMessageLimit, screenTransport, screenStream, screenFps }
}
