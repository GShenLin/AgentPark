import { computed, onBeforeUnmount, ref } from 'vue'
import { getActiveApiBase } from '../api'
import { createVoiceCall, describeVoiceCall, voiceRequest, type VoiceTarget } from '../voiceApi'
import type { VolcRtcConnection } from '../voice/VolcRtcConnection'
import { voiceProtocol, type VoiceEvent, type VoiceProtocolAdapter } from '../voice/voiceProtocol'
import { VoiceTranscript, type VoiceFinish } from '../voice/voiceTranscript'
import { deliverVoiceToolResult } from '../voice/voiceToolFeedback'
import { runVoiceTask } from '../voice/voiceTaskRunner'
import { syncVoiceContext } from '../voice/voiceContextSync'
import type { VoiceComposerEdit, VoiceComposerSnapshot } from '../voice/voiceComposer'
import type { AnnotationDrawing } from '../voice/screenAnnotations'

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
  contextStarted?: boolean
}

export function useNodeVoiceCall(options: { media?: VoiceMedia; readComposer?: (target: VoiceTarget) => VoiceComposerSnapshot;
  annotateScreen?: (drawing: AnnotationDrawing) => Promise<string>;
  captureScreen?: (id: string, displayId: string) => Promise<string>;
  editComposer?: (target: VoiceTarget, edit: VoiceComposerEdit) => VoiceComposerSnapshot } = {}) {
  const active = ref(false), connected = ref(false), muted = ref(false)
  const stage = ref(''), error = ref(''), taskStatus = ref('')
  const lines = ref<Line[]>([])
  const userCaption = ref(''), assistantCaption = ref('')
  const recordSaving = ref(false), recordError = ref('')
  const contextStatus = ref(''), feedbackStatus = ref('')
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
    call = undefined; active.value = false; connected.value = false; muted.value = false
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

  function operationFailed(candidate: Call, text: string) {
    if (isCurrent(candidate)) error.value = text
  }

  async function delegate(candidate: Call, event: Extract<VoiceEvent, { kind: 'delegation' | 'composer' | 'composer-edit' | 'annotation' | 'screenshot' | 'tool-error' }>) {
    const identity = JSON.stringify(event)
    const previous = candidate.seen.get(event.id)
    if (previous !== undefined) {
      if (previous !== identity) throw new Error('重复的语音任务编号包含不同内容。')
      return
    }
    candidate.seen.set(event.id, identity)
    if (!candidate.session) throw new Error('语音任务没有绑定节点会话。')
    taskStatus.value = '正在提交节点任务…'
    try {
      await runVoiceTask({ target: candidate.target, session: candidate.session, protocol: candidate.protocol!,
        signal: candidate.controller.signal, event, readComposer: options.readComposer, editComposer: options.editComposer,
        annotateScreen: options.annotateScreen, captureScreen: options.captureScreen,
        status: text => { if (isCurrent(candidate)) taskStatus.value = text },
        feedback: text => { if (isCurrent(candidate)) feedbackStatus.value = text },
      })
    } catch (e) {
      if (!isCurrent(candidate)) return
      const message = e instanceof Error ? e.message : String(e)
      error.value = `本次工具操作失败，通话继续：${message}`
      taskStatus.value = error.value
      const protocol = candidate.protocol!
      await deliverVoiceToolResult({ target: candidate.target, session: candidate.session, protocol, signal: candidate.controller.signal },
        event.id, { status: 'failed', text: `工具执行失败：${message}。未确认执行成功。` })
    }
  }

  function receive(candidate: Call, raw: string) {
    if (!isCurrent(candidate)) return
    try {
      if (!candidate.protocol?.parse) throw new Error('语音通话尚未协商数据通道协议。')
      receiveEvent(candidate, candidate.protocol.parse(raw))
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      if (connected.value) operationFailed(candidate, `本次语音事件未处理，通话继续：${message}`)
      else fail(candidate, message)
    }
  }

  function receiveEvent(candidate: Call, event: VoiceEvent) {
    if (!isCurrent(candidate)) return
    try {
      if (event.kind === 'error') { fail(candidate, event.text); return }
      if (event.kind === 'warning') { operationFailed(candidate, event.text); return }
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
        if (candidate.session && candidate.protocol?.resultDelivery === 'data-channel' && !candidate.contextStarted) {
          candidate.contextStarted = true
          void syncVoiceContext(candidate.target, candidate.session, candidate.protocol.dialogue, candidate.controller.signal,
            text => { if (isCurrent(candidate)) contextStatus.value = text },
          ).catch(cause => { if (isCurrent(candidate)) contextStatus.value = `聊天同步失败：${String(cause)}` })
        }
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
      } else if (event.kind === 'delegation' || event.kind === 'composer' || event.kind === 'composer-edit' || event.kind === 'annotation' || event.kind === 'screenshot' || event.kind === 'tool-error') {
        void delegate(candidate, event).catch(e => operationFailed(candidate, `工具反馈失败，通话继续：${e instanceof Error ? e.message : String(e)}`))
      }
    } catch (e) { operationFailed(candidate, `本次语音事件处理失败，通话继续：${e instanceof Error ? e.message : String(e)}`) }
  }

  async function start(node: string, graph: string) {
    if (active.value) return
    if (pendingRecord) {
      await saveRecord()
      if (pendingRecord) return
    }
    error.value = ''; stage.value = '正在请求麦克风权限…'; lines.value = []
    contextStatus.value = ''; feedbackStatus.value = ''
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
      const description = await describeVoiceCall(candidate.target, candidate.controller.signal)
      if (!isCurrent(candidate)) return
      stage.value = '正在建立语音连接…'
      if (description.transport === 'volcengine-rtc') {
        candidate.timer = setTimeout(() => fail(candidate, 'RTC 语音连接超时，请重试。'), 60_000)
        const { VolcRtcConnection } = await import('../voice/VolcRtcConnection')
        if (!isCurrent(candidate)) return
        const answer = await createVoiceCall(candidate.target, undefined, candidate.controller.signal)
        if (!isCurrent(candidate)) {
          await voiceRequest(candidate.target, `/${encodeURIComponent(answer.session_id)}`, { method: 'DELETE' }); return
        }
        candidate.session = answer.session_id
        if (answer.transport !== 'volcengine-rtc') throw new Error('语音供应商已改变，请重新拨号。')
        candidate.protocol = voiceProtocol(answer.protocol)
        candidate.rtc = new VolcRtcConnection(candidate.target, answer.session_id, answer, candidate.controller.signal, {
          event: event => receiveEvent(candidate, event), audio: receiveAudio, error: message => fail(candidate, message),
        })
        await candidate.rtc.connect(stream)
        return
      }
      const pc = new RTCPeerConnection({ iceServers: description.iceServers, iceTransportPolicy: 'all' }); candidate.pc = pc
      stream.getAudioTracks().forEach(track => pc.addTrack(track, stream))
      pc.ontrack = event => receiveAudio(new MediaStream([event.track]))
      pc.onconnectionstatechange = () => {
        if (candidate.protocol?.resultDelivery === 'data-channel') candidate.protocol.dialogue.transportAvailable(pc.connectionState === 'connected')
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
      const offer = await pc.createOffer()
      if (!isCurrent(candidate)) return
      await pc.setLocalDescription(offer)
      if (!isCurrent(candidate)) return
      // Start signaling immediately. The browser gathers candidates and checks
      // direct/relay connectivity while the provider prepares its SDP answer.
      const answer = await createVoiceCall(candidate.target, offer.sdp, candidate.controller.signal)
      if (!isCurrent(candidate)) {
        await voiceRequest(candidate.target, `/${encodeURIComponent(answer.session_id)}`, { method: 'DELETE' })
        return
      }
      candidate.session = answer.session_id
      if (answer.transport !== 'webrtc') throw new Error('语音供应商已改变，请重新拨号。')
      candidate.protocol = voiceProtocol(answer.protocol, event => send(candidate, event))
      if (candidate.protocol.resultDelivery === 'data-channel') {
        candidate.feedbackTimer = setInterval(() => {
          if (!isCurrent(candidate) || candidate.protocol?.resultDelivery !== 'data-channel') return
          try { candidate.protocol.dialogue.flush() }
          catch (e) { fail(candidate, e instanceof Error ? e.message : String(e)) }
        }, 250)
      }
      stage.value = '通话已创建，正在连接音频…'
      // Session creation does not consume the media connection's time.
      candidate.timer = setTimeout(() => fail(candidate,
        `语音网络连接超时，请重试。连接状态：${pc.connectionState}；数据通道：${dc.readyState}。`), 60_000)
      await pc.setRemoteDescription({ type: 'answer', sdp: answer.sdp })
    } catch (e) { fail(candidate, e instanceof Error ? e.message : String(e)) }
  }

  onBeforeUnmount(() => stop())
  function desktopSession() {
    if (!call?.session || !connected.value) throw new Error('请先接通语音。')
    return { target: call.target, session: call.session }
  }
  return { active, connected, muted, stage, error, taskStatus, lines, userCaption, assistantCaption,
    contextStatus, feedbackStatus,
    supported, start, hangup, toggleMute, recordSaving, recordError, saveRecord,
    desktopSession }
}
