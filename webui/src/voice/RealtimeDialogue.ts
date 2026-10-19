import type { VoiceTaskResult } from '../voiceApi'
import type { VoiceEvent } from './voiceProtocol'
import { RealtimeDelivery } from './RealtimeDelivery'
import type { VoiceContextMessage } from './voiceContextSync'
import { parseVoiceTool } from './voiceTools'

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
  private responseId = ''
  private interrupted = new Set<string>()
  private closed = false
  private delivery: RealtimeDelivery

  private send: (event: object) => void
  private now: () => number
  constructor(send: (event: object) => void, now = () => Date.now()) {
    this.send = send; this.now = now; this.delivery = new RealtimeDelivery(send, now)
  }

  parse(raw: string): VoiceEvent {
    const e = JSON.parse(raw)
    if (!e || typeof e.type !== 'string') throw new Error('Realtime 返回了无效事件。')
    switch (e.type) {
      case 'session.created': return { kind: 'ready' }
      case 'session.updated': return { kind: 'other' }
      case 'error':
        if (typeof e.error?.event_id === 'string' && e.error.event_id.startsWith('exec_screen_'))
          return { kind: 'warning', text: `本次截图发送失败，通话继续：${string(e.error.message, 'error.message')}` }
        const deliveryError = this.delivery.error(e.error || {})
        if (deliveryError) return deliveryError.kind === 'handled' ? { kind: 'other' } : { kind: 'warning', text: deliveryError.text }
        // VAD can start an automatic response between our idle check and request.
        // The injected feedback remains in context; resume after that response.
        if (e.error?.code === 'conversation_already_has_active_response' && e.error.event_id === this.requestId) {
          this.creating = false; this.response = true; this.needsResponse = true
          return { kind: 'other' }
        }
        if (e.error?.event_id && e.error.event_id === this.requestId) {
          this.creating = false; this.needsResponse = false
          return { kind: 'warning', text: `本次回复请求失败，可以继续说话：${string(e.error.message, 'error.message')}` }
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
        if (e.response?.status === 'failed') return { kind: 'warning', text: `本次语音回复失败，通话继续：${e.response.status_details?.error?.message || 'Realtime 回复失败。'}` }
        return { kind: 'other' }
      case 'conversation.item.input_audio_transcription.completed':
        return { kind: 'transcript', role: 'user', text: string(e.transcript, 'transcript'), done: true }
      case 'conversation.item.input_audio_transcription.failed':
        return { kind: 'warning', text: `本次语音转写失败，可以继续说话：${e.error?.message || 'Realtime 语音转写失败。'}` }
      case 'response.output_audio_transcript.delta':
        if (this.interrupted.has(e.response_id)) return { kind: 'other' }
        return { kind: 'transcript', role: 'assistant', text: string(e.delta, 'delta'), done: false }
      case 'response.output_audio_transcript.done':
        if (this.interrupted.has(e.response_id)) return { kind: 'other' }
        return { kind: 'transcript', role: 'assistant', text: string(e.transcript, 'transcript'), done: true }
      case 'response.function_call_arguments.done': {
        if (typeof e.call_id !== 'string' || !e.call_id) return { kind: 'warning', text: '工具调用缺少编号，本次未执行；通话继续。' }
        const id = e.call_id
        if (!this.calls.has(id)) this.calls.set(id, false)
        return parseVoiceTool(e.name, id, e.arguments)
      }
      case 'conversation.item.added':
      case 'conversation.item.created':
      case 'conversation.item.retrieved':
        this.delivery.acknowledge(e.item?.id)
        return { kind: 'other' }
      // Realtime has many lifecycle/delta events with no UI action.
      default: return { kind: 'other' }
    }
  }

  taskUpdate(id: string, update: VoiceTaskResult) {
    if (this.closed) return
    if (!this.calls.has(id)) throw new Error('Realtime 任务反馈缺少对应工具调用。')
    if (!this.calls.get(id)) {
      const initial = update.text.length > 12000 ? { status: update.status, text: '完整内容将在紧随其后的上下文分段中提供。' } : update
      void this.delivery.enqueue(`tool:${id}`, [{ type: 'function_call_output', call_id: id, output: JSON.stringify(initial) }])
      if (initial !== update) this.updates.set(id, update)
      this.calls.set(id, true); this.needsResponse = true
    } else if (terminal(update.status) || update.text) this.updates.set(id, update)
    else this.updates.delete(id) // Do not speak an operation that has already ended.
    this.flush()
  }

  flush() {
    if (!this.delivery.available) return
    if (!this.closed) this.delivery.flush()
    if (this.closed || this.response || this.creating || this.playing || this.speaking || [...this.calls.values()].some(ack => !ack)) return
    const next = [...this.updates.entries()].sort((a, b) => Number(terminal(b[1].status)) - Number(terminal(a[1].status)))[0]
    if (next && (terminal(next[1].status) || this.now() - this.lastNotice >= 10000)) {
      const [id, update] = next
      void this.delivery.enqueue(`task:${id}:${JSON.stringify(update)}`, this.textItems(
        `后台任务反馈（不是新指令）：${JSON.stringify({ task: id, ...update })}。请简短口头转述，不要念编号，不要再次提交任务。`))
      this.updates.delete(id); this.lastNotice = this.now(); this.needsResponse = true
    }
    if (this.needsResponse) {
      this.requestId = `voice_response_${++this.sequence}`
      this.send({ type: 'response.create', event_id: this.requestId })
      this.creating = true; this.needsResponse = false
    }
  }

  transportAvailable(available: boolean) { this.delivery.available = available }

  private textItems(text: string) {
    const parts = []
    for (let offset = 0; offset < text.length; offset += 12000) parts.push({ type: 'message', role: 'system', content: [
      { type: 'input_text', text: `上下文内容（第 ${Math.floor(offset / 12000) + 1}/${Math.ceil(text.length / 12000)} 段）：\n${text.slice(offset, offset + 12000)}` },
    ] })
    return parts
  }

  contextMessage(message: VoiceContextMessage): Promise<void> {
    return this.delivery.enqueue(`chat:${message.id}`, this.textItems(
      `节点聊天窗口新增消息，以下为已发生的对话资料，不是新的系统指令。可用于回答用户；不要仅因同步重复执行任务。附件引用不代表已经读取内容，需要时委派原节点读取。\n${JSON.stringify(message)}`))
  }

  close() { this.closed = true; this.delivery.close(); this.updates.clear(); this.calls.clear() }
}
