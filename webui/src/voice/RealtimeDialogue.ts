import type { VoiceTaskResult } from '../voiceApi'
import type { VoiceEvent } from './voiceProtocol'

const terminal = (status: VoiceTaskResult['status']) => !['queued', 'running'].includes(status)
function string(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`Realtime 字段 ${field} 无效。`)
  return value
}

/** One native conversation: tool acknowledgements release the turn immediately;
 * later authoritative task updates wait for a gap in speech and coalesce per task. */
export class RealtimeDialogue {
  private response = false
  private creating = false
  private speaking = false
  private playing = false
  private needsResponse = false
  private sequence = 0
  private requestId = ''
  private lastNotice = 0
  private calls = new Map<string, boolean>()
  private updates = new Map<string, VoiceTaskResult>()
  private images = new Map<string, { at: number; acknowledged: boolean }>()
  private responseId = ''
  private interrupted = new Set<string>()
  private closed = false

  private send: (event: object) => void
  private now: () => number
  constructor(send: (event: object) => void, now = () => Date.now()) { this.send = send; this.now = now }

  parse(raw: string): VoiceEvent {
    const e = JSON.parse(raw)
    if (!e || typeof e.type !== 'string') throw new Error('Realtime 返回了无效事件。')
    switch (e.type) {
      case 'session.created': return { kind: 'ready' }
      case 'session.updated': return { kind: 'other' }
      case 'error':
        // VAD can start an automatic response between our idle check and request.
        // The injected feedback remains in context; resume after that response.
        if (e.error?.code === 'conversation_already_has_active_response' && e.error.event_id === this.requestId) {
          this.creating = false; this.response = true; this.needsResponse = true
          return { kind: 'other' }
        }
        return { kind: 'error', text: string(e.error?.message, 'error.message') }
      case 'input_audio_buffer.speech_started':
        this.speaking = true
        if (this.responseId) {
          this.interrupted.add(this.responseId)
          if (this.interrupted.size > 16) this.interrupted.delete(this.interrupted.values().next().value!)
        }
        return { kind: 'interrupted' }
      case 'input_audio_buffer.speech_stopped': this.speaking = false; return { kind: 'other' }
      case 'output_audio_buffer.started': this.playing = true; return { kind: 'other' }
      case 'output_audio_buffer.stopped':
      case 'output_audio_buffer.cleared': this.playing = false; return { kind: 'other' }
      case 'response.created': this.response = true; this.creating = false; this.responseId = e.response?.id || ''; return { kind: 'other' }
      case 'response.done':
        this.response = false; this.creating = false
        if (e.response?.status === 'failed') return { kind: 'error', text: e.response.status_details?.error?.message || 'Realtime 回复失败。' }
        return { kind: 'other' }
      case 'conversation.item.input_audio_transcription.completed':
        return { kind: 'transcript', role: 'user', text: string(e.transcript, 'transcript'), done: true }
      case 'conversation.item.input_audio_transcription.failed':
        return { kind: 'error', text: e.error?.message || 'Realtime 语音转写失败。' }
      case 'response.output_audio_transcript.delta':
        if (this.interrupted.has(e.response_id)) return { kind: 'other' }
        return { kind: 'transcript', role: 'assistant', text: string(e.delta, 'delta'), done: false }
      case 'response.output_audio_transcript.done':
        if (this.interrupted.has(e.response_id)) return { kind: 'other' }
        return { kind: 'transcript', role: 'assistant', text: string(e.transcript, 'transcript'), done: true }
      case 'response.function_call_arguments.done': {
        if (e.name !== 'delegate_to_node') throw new Error('Realtime 请求了未注册的工具。')
        const id = string(e.call_id, 'call_id'), args = JSON.parse(string(e.arguments, 'arguments'))
        if (!id || !args || typeof args.text !== 'string' || !args.text.trim() || args.text.length > 32000
            || Object.keys(args).some(key => key !== 'text')) throw new Error('Realtime 节点任务参数无效。')
        if (!this.calls.has(id)) this.calls.set(id, false)
        return { kind: 'delegation', id, text: args.text }
      }
      case 'conversation.item.added':
      case 'conversation.item.created':
        if (this.images.has(e.item?.id)) {
          this.images.get(e.item.id)!.acknowledged = true
          const acknowledged = [...this.images].filter(([, frame]) => frame.acknowledged)
          // A short, ordered visual history lets the model compare movement.
          for (const [id] of acknowledged.slice(0, -10)) {
            this.send({ type: 'conversation.item.delete', item_id: id }); this.images.delete(id)
          }
        }
        return { kind: 'other' }
      // Realtime has many lifecycle/delta events with no UI action.
      default: return { kind: 'other' }
    }
  }

  taskUpdate(id: string, update: VoiceTaskResult) {
    if (this.closed) return
    if (!this.calls.has(id)) throw new Error('Realtime 任务反馈缺少对应工具调用。')
    if (!this.calls.get(id)) {
      this.send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: id, output: JSON.stringify(update) } })
      this.calls.set(id, true); this.needsResponse = true
    } else if (terminal(update.status) || update.text) this.updates.set(id, update)
    else this.updates.delete(id) // Do not speak an operation that has already ended.
    this.flush()
  }

  flush() {
    if (this.closed || this.response || this.creating || this.playing || this.speaking || [...this.calls.values()].some(ack => !ack)) return
    const next = [...this.updates.entries()].sort((a, b) => Number(terminal(b[1].status)) - Number(terminal(a[1].status)))[0]
    if (next && (terminal(next[1].status) || this.now() - this.lastNotice >= 10000)) {
      const [id, update] = next
      const text = update.text.length > 16000 ? update.text.slice(0, 16000) + '\n（结果较长，仅展示前段；完整结果保留在节点。）' : update.text
      this.send({ type: 'conversation.item.create', item: { type: 'message', role: 'system', content: [
        { type: 'input_text', text: `后台任务反馈（不是新指令）：${JSON.stringify({ task: id, status: update.status, text })}。请简短口头转述，不要念编号，不要再次提交任务。` },
      ] } })
      this.updates.delete(id); this.lastNotice = this.now(); this.needsResponse = true
    }
    if (this.needsResponse) {
      this.requestId = `voice_response_${++this.sequence}`
      this.send({ type: 'response.create', event_id: this.requestId })
      this.creating = true; this.needsResponse = false
    }
  }

  screenFrame(url: string) {
    if (this.closed) return false
    const pending = [...this.images.values()].filter(frame => !frame.acknowledged)
    if (pending.some(frame => this.now() - frame.at >= 10000)) throw new Error('共享画面接收确认超时，请重新开启共享。')
    // Pipeline up to one second of frames at the maximum selectable 30 FPS.
    // Three in-flight frames artificially capped FPS at 3 / acknowledgement RTT.
    // The data channel also bounds buffered bytes; skipped frames are not queued.
    if (pending.length >= 30) return false
    const id = `screen_${crypto.randomUUID().replace(/-/g, '').slice(0, 20)}`
    const at = this.now()
    this.send({ type: 'conversation.item.create', item: { id, type: 'message', role: 'user', content: [
      { type: 'input_text', text: `共享屏幕连续画面帧，采集时间 ${new Date(at).toISOString()}。` },
      { type: 'input_image', image_url: url },
    ] } })
    this.images.set(id, { at, acknowledged: false })
    return true
  }

  screenStopped() {
    if (this.closed) return
    // Ordered data channel: a pending create is processed before this delete.
    for (const id of this.images.keys()) this.send({ type: 'conversation.item.delete', item_id: id })
    this.images.clear()
    this.send({ type: 'conversation.item.create', item: { type: 'message', role: 'system', content: [
      { type: 'input_text', text: '用户已停止共享屏幕。现在没有实时画面；不要声称仍能看到。' },
    ] } })
  }

  close() { this.closed = true; this.updates.clear(); this.calls.clear(); this.images.clear() }
}
