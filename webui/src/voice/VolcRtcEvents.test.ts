import { expect, it } from 'vitest'
import { VolcRtcEvents } from './VolcRtcEvents'
import { VoiceTranscript } from './voiceTranscript'

function tlv(type: string, data: object): ArrayBuffer {
  const bytes = new TextEncoder().encode(JSON.stringify(data)), result = new ArrayBuffer(8 + bytes.length)
  new Uint8Array(result).set(new TextEncoder().encode(type))
  new DataView(result).setUint32(4, bytes.length)
  new Uint8Array(result, 8).set(bytes)
  return result
}

it('maps official tool calls exactly once upstream and rejects unrelated tools or malformed envelopes', () => {
  const parser = new VolcRtcEvents('user', 'bot')
  const tool = { id: 'c1', type: 'function', function: { name: 'delegate_to_node', arguments: '{"text":"读取文件"}' } }
  expect(parser.parse(tlv('tool', { tool_calls: [tool] }))).toEqual([{ kind: 'delegation', id: 'c1', text: '读取文件' }])
  expect(parser.parse(tlv('info', { event_type: 'function_calling' }))).toEqual([])
  expect(() => parser.parse(tlv('tool', { tool_calls: [{ ...tool, function: { ...tool.function, name: 'execute_arbitrary' } }] }))).toThrow('未声明')
  const damaged = tlv('tool', { tool_calls: [] }); new DataView(damaged).setUint32(4, 999)
  expect(() => parser.parse(damaged)).toThrow('长度不匹配')
})

it('keeps cumulative ASR and segmented assistant speech without duplicating durable transcripts', () => {
  const parser = new VolcRtcEvents('user', 'bot'), transcript = new VoiceTranscript()
  const send = (userId: string, sequence: number, text: string, definite: boolean, paragraph: boolean) => {
    for (const event of parser.parse(tlv('subv', { type: 'subtitle', data: [{ userId, roundId: 1, sequence, text, definite, paragraph }] }))) {
      if (event.kind === 'transcript') transcript.add(event)
    }
  }
  send('user', 1, '你好', false, false); send('user', 2, '你好，查个文件。', true, true)
  send('bot', 1, '好的，', true, false); send('bot', 2, '正在', false, false)
  send('bot', 3, '正在查询。', true, true); send('bot', 3, '正在查询。', true, true)
  expect(transcript.finish('ended').lines.map(line => line.text)).toEqual(['你好，查个文件。', '好的，正在查询。'])
})

it('does not replay stale assistant subtitles after interruption and surfaces provider errors', () => {
  const parser = new VolcRtcEvents('user', 'bot')
  const subtitle = { type: 'subtitle', data: [{ userId: 'bot', roundId: 1, sequence: 1, text: '没说完', definite: false, paragraph: false }] }
  parser.parse(tlv('subv', subtitle))
  expect(parser.parse(tlv('conv', { Stage: { Code: 4 } }))).toEqual([{ kind: 'interrupted', role: 'assistant' }])
  expect(parser.parse(tlv('subv', subtitle))).toEqual([])
  expect(parser.parse(tlv('conv', { Stage: { Code: 0 }, ErrorInfo: { Code: 401, Reason: 'ASR denied' } }))[0]).toEqual({ kind: 'error', text: '火山语音服务错误：401 ASR denied' })
})

it('keeps the user utterance intact when it overlaps an assistant interruption', () => {
  const parser = new VolcRtcEvents('user', 'bot'), transcript = new VoiceTranscript()
  const receive = (type: string, data: object) => {
    for (const event of parser.parse(tlv(type, data))) {
      if (event.kind === 'transcript') transcript.add(event)
      if (event.kind === 'interrupted') transcript.interrupt(event.role)
    }
  }
  const subtitle = (userId: string, text: string, paragraph: boolean) => ({ type: 'subtitle', data: [{
    userId, text, paragraph, definite: paragraph, roundId: 2, sequence: paragraph ? 2 : 1,
  }] })
  receive('subv', subtitle('bot', '还没说完', false))
  receive('subv', subtitle('user', '等一下', false))
  receive('conv', { Stage: { Code: 4 } })
  receive('subv', subtitle('user', '等一下，换一个问题。', true))
  expect(transcript.finish('ended').lines.map(line => [line.text, line.incomplete])).toEqual([
    ['还没说完', true], ['等一下，换一个问题。', false],
  ])
})
