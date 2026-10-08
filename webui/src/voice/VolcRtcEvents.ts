import type { VoiceEvent } from './voiceProtocol'

type Segment = { sequence: number; text: string; definite: boolean }
type Turn = { round: number; segments: Segment[]; complete: boolean }

/** Official RTC TLV messages. ASR is cumulative; assistant subtitles are segmented. */
export class VolcRtcEvents {
  private turns = new Map<string, Turn>()
  private user: string
  private bot: string
  constructor(user: string, bot: string) { this.user = user; this.bot = bot }

  parse(buffer: ArrayBuffer): VoiceEvent[] {
    if (buffer.byteLength < 8) throw new Error('火山 RTC 消息头不完整。')
    const view = new DataView(buffer), decoder = new TextDecoder('utf-8', { fatal: true })
    const magic = decoder.decode(new Uint8Array(buffer, 0, 4))
    if (view.getUint32(4, false) !== buffer.byteLength - 8) throw new Error('火山 RTC 消息长度不匹配。')
    // info is a tool-call notification, not another executable invocation.
    if (!['tool', 'subv', 'conv'].includes(magic)) return []
    const data = JSON.parse(decoder.decode(new Uint8Array(buffer, 8)))
    if (magic === 'tool') {
      if (!Array.isArray(data.tool_calls)) throw new Error('火山工具调用缺少 tool_calls。')
      return data.tool_calls.map((item: { id: string; type: string; function: { name: string; arguments: string } }) => {
        if (item.type !== 'function' || item.function?.name !== 'delegate_to_node'
          || typeof item.id !== 'string' || !item.id || typeof item.function.arguments !== 'string') throw new Error('火山返回了未声明的节点工具调用。')
        const args = JSON.parse(item.function.arguments)
        if (typeof args?.text !== 'string' || !args.text.trim() || Object.keys(args).some(key => key !== 'text')) throw new Error('火山节点工具参数格式错误。')
        return { kind: 'delegation', id: item.id, text: args.text }
      })
    }
    if (magic === 'conv') {
      if (!Number.isInteger(data.Stage?.Code) || data.Stage.Code < 0 || data.Stage.Code > 5) throw new Error('火山会话状态格式错误。')
      if (data.Stage.Code === 0) return [{ kind: 'error', text: `火山语音服务错误：${data.ErrorInfo?.Code} ${data.ErrorInfo?.Reason}` }]
      if (data.Stage.Code === 4) {
        const assistant = this.turns.get('assistant')
        if (assistant) assistant.complete = true
        return [{ kind: 'interrupted', role: 'assistant' }]
      }
      return [] // Audio subscription, not a status message, confirms readiness.
    }
    if (data.type !== 'subtitle' || !Array.isArray(data.data)) throw new Error('火山字幕消息格式错误。')
    const events: VoiceEvent[] = []
    for (const item of data.data) {
      if (item.userId !== this.user && item.userId !== this.bot) throw new Error('火山字幕来源不属于当前通话。')
      if (typeof item.text !== 'string' || typeof item.paragraph !== 'boolean' || typeof item.definite !== 'boolean'
        || !Number.isInteger(item.sequence) || !Number.isInteger(item.roundId)) throw new Error('火山字幕字段不完整。')
      const role = item.userId === this.user ? 'user' : 'assistant'
      let turn = this.turns.get(role)
      if (turn && item.roundId < turn.round) continue
      if (!turn || turn.round !== item.roundId) {
        if (turn && !turn.complete) events.push({ kind: 'interrupted', role })
        turn = { round: item.roundId, segments: [], complete: false }; this.turns.set(role, turn)
      }
      if (turn.complete) continue
      const last = turn.segments[turn.segments.length - 1]
      if (last && item.sequence < last.sequence) continue
      if (role === 'user') turn.segments = [{ sequence: item.sequence, text: item.text, definite: item.definite }]
      else if (last?.sequence === item.sequence || (last && !last.definite)) {
        turn.segments[turn.segments.length - 1] = { sequence: item.sequence, text: item.text, definite: item.definite }
      } else turn.segments.push({ sequence: item.sequence, text: item.text, definite: item.definite })
      turn.complete = item.paragraph
      events.push({ kind: 'transcript', role, text: turn.segments.map(s => s.text).join(''), done: turn.complete, replace: true })
    }
    return events
  }
}
