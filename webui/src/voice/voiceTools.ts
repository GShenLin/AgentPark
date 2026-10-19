import type { VoiceEvent } from './voiceProtocol'
import { parseAnnotation } from './screenAnnotations'

export type VoiceToolEvent = Extract<VoiceEvent, { kind: 'delegation' | 'composer' | 'composer-edit' | 'annotation' | 'screenshot' | 'tool-error' }>

/** Model-generated arguments are fallible task input, never session health. */
export function parseVoiceTool(name: unknown, id: string, raw: unknown): VoiceToolEvent {
  try {
    if (typeof name !== 'string' || !['delegate_to_node', 'read_composer_input', 'edit_composer_input', 'annotate_screen', 'capture_execution_screen'].includes(name)) {
      throw new Error('请求了未注册的工具，请使用当前会话已提供的工具。')
    }
    if (typeof raw !== 'string') throw new Error('工具参数必须是 JSON 字符串。')
    let args
    try { args = JSON.parse(raw) } catch { throw new Error('工具参数不是有效的 JSON，请修正后重试。') }
    if (name === 'annotate_screen') return { kind: 'annotation', id, drawing: parseAnnotation(args) }
    if (!args || typeof args !== 'object' || Array.isArray(args)) throw new Error('工具参数必须是对象。')
    if (name === 'capture_execution_screen') {
      if (typeof args.display_id !== 'string' || args.display_id.length > 100
          || Object.keys(args).some(key => key !== 'display_id')) throw new Error('截图参数无效，请提供 display_id，空字符串表示主显示器。')
      return { kind: 'screenshot', id, display_id: args.display_id }
    }
    if (name === 'edit_composer_input') {
      if (typeof args.text !== 'string' || typeof args.expected_text !== 'string'
          || args.text.length > 128000 || args.expected_text.length > 128000
          || Object.keys(args).some(key => !['text', 'expected_text'].includes(key))) throw new Error('草稿修改参数无效，请先读取原文，再提供 expected_text 和修改后的完整 text。')
      return { kind: 'composer-edit', id, text: args.text, expected_text: args.expected_text }
    }
    if (typeof args.text !== 'string' || !args.text.trim() || args.text.length > 32000
        || Object.keys(args).some(key => key !== 'text')) throw new Error('节点工具参数无效，请只提供非空的 text 字符串，最多 32000 字符。')
    return { kind: name === 'read_composer_input' ? 'composer' : 'delegation', id, text: args.text }
  } catch (cause) {
    return { kind: 'tool-error', id, text: `本次工具未执行：${cause instanceof Error ? cause.message : String(cause)} 通话仍在继续，请修正本次请求后重试。` }
  }
}
