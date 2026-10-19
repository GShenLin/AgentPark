import { expect, it, vi } from 'vitest'
import { createVoiceComposers } from './voiceComposer'
import { RealtimeDialogue } from './RealtimeDialogue'
import { runVoiceTask } from './voiceTaskRunner'

const target = { base: 'http://device', graph: 'graph', node: 'GPT' }
function setup() {
  const composers = createVoiceComposers()
  const state = { target, text: ' 原始\n草稿 ', attachments: [{ name: 'photo.png', path: '/photo.png' }], uploading: false, locked: false }
  const write = vi.fn((text: string) => { state.text = text })
  const unregister = composers.register(() => state, write)
  return { composers, state, write, unregister }
}

it('replaces, appends and clears exact draft text while preserving attachments', () => {
  const h = setup(), files = h.state.attachments
  for (const text of [' 改写后的\n正文 ', ' 改写后的\n正文 \n追加一句', '']) {
    const original = h.composers.read(target)
    expect(h.composers.edit(target, { expected_text: original.text, text })).toEqual({ text, resources: original.resources })
    expect(h.state.text).toBe(text)
    expect(h.state.attachments).toBe(files)
  }
})

it('rejects stale text, a sending composer and a pending upload without touching the draft', () => {
  const h = setup(), original = h.state.text
  h.state.text += '用户刚输入的新内容'
  expect(() => h.composers.edit(target, { expected_text: original, text: '覆盖' })).toThrow('已变化')
  h.state.locked = true
  expect(() => h.composers.edit(target, { expected_text: h.state.text, text: '覆盖' })).toThrow('正在发送')
  h.state.locked = false; h.state.uploading = true
  expect(() => h.composers.edit(target, { expected_text: h.state.text, text: '覆盖' })).toThrow('上传')
  expect(h.write).not.toHaveBeenCalled()
  expect(h.state.text).toContain('用户刚输入的新内容')
})

it('rejects another device, graph or node, ambiguous editors, and an unmounted editor', () => {
  const h = setup(), edit = { expected_text: h.state.text, text: '修改' }
  for (const other of [{ ...target, base: 'other' }, { ...target, graph: 'other' }, { ...target, node: 'other' }]) {
    expect(() => h.composers.edit(other, edit)).toThrow('打开')
  }
  const remove = h.composers.register(() => h.state, h.write)
  expect(() => h.composers.edit(target, edit)).toThrow('多个')
  remove(); h.unregister()
  expect(() => h.composers.edit(target, edit)).toThrow('打开')
  expect(h.write).not.toHaveBeenCalled()
})

it('strictly validates edit tool arguments including exact whitespace and empty replacement', () => {
  const dialogue = new RealtimeDialogue(vi.fn())
  const parse = (args: unknown) => dialogue.parse(JSON.stringify({ type: 'response.function_call_arguments.done',
    name: 'edit_composer_input', call_id: 'edit', arguments: JSON.stringify(args) }))
  expect(parse({ expected_text: ' \n ', text: '' })).toEqual({ kind: 'composer-edit', id: 'edit', expected_text: ' \n ', text: '' })
  for (const args of [{ text: 'x' }, { expected_text: 2, text: 'x' }, { expected_text: '', text: null },
    { expected_text: '', text: 'x', send: true }, { expected_text: '', text: 'x'.repeat(128001) }]) {
    expect(parse(args)).toMatchObject({ kind: 'tool-error', text: expect.stringContaining('参数无效') })
  }
  dialogue.close()
})

it('executes a parsed tool locally and returns a receipt; cancelled calls cannot edit', async () => {
  const h = setup(), send = vi.fn(), dialogue = new RealtimeDialogue(send), controller = new AbortController()
  const event = dialogue.parse(JSON.stringify({ type: 'response.function_call_arguments.done', name: 'edit_composer_input',
    call_id: 'edit', arguments: JSON.stringify({ expected_text: h.state.text, text: '新的草稿' }) }))
  if (event.kind !== 'composer-edit') throw new Error('Expected composer edit')
  const options = { target, session: 'session', event, signal: controller.signal, status: vi.fn(), feedback: vi.fn(),
    protocol: { resultDelivery: 'data-channel' as const, dialogue, parse: (raw: string) => dialogue.parse(raw) },
    editComposer: h.composers.edit }
  await runVoiceTask(options)
  expect(h.state.text).toBe('新的草稿')
  const receipt = JSON.parse(send.mock.calls[0]![0].item.output)
  expect(receipt.status).toBe('completed')
  expect(JSON.parse(receipt.text)).toMatchObject({ source: 'unsent_composer_edit', text: '新的草稿', attachment_count: 1 })
  controller.abort()
  await expect(runVoiceTask(options)).rejects.toThrow()
  expect(h.write).toHaveBeenCalledOnce()
  dialogue.close()
})
