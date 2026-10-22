import { describe, expect, it } from 'vitest'
import { readToolPrompts, setToolPrompt, toolPromptEntries } from '../src/toolPromptEditor'

describe('tool prompt editing', () => {
  it('preserves toolset membership while editing, round-tripping and restoring multiline prompts', () => {
    const original = { toolsets: { custom: { description: 'Group', tools: ['file_read_tools:read_file'] } }, deleted_toolsets: ['old'] }
    const saved = setToolPrompt(original, 'read_file', 'Read carefully.\n保留上下文。')
    expect(readToolPrompts(JSON.parse(JSON.stringify(saved)))).toEqual({ read_file: 'Read carefully.\n保留上下文。' })
    expect(saved.toolsets).toEqual(original.toolsets)
    expect(saved.deleted_toolsets).toEqual(['old'])
    expect(readToolPrompts(original)).toEqual({})
    expect(readToolPrompts(setToolPrompt(saved, 'read_file', null))).toEqual({})
  })

  it('accepts exact external names and distinguishes empty text from reset', () => {
    const saved = setToolPrompt({}, 'mcp__server__query', '')
    expect(readToolPrompts(saved)).toEqual({ mcp__server__query: '' })
    expect(toolPromptEntries([], readToolPrompts(saved)!)).toEqual([{ name: 'mcp__server__query', defaults: [] }])
    expect(toolPromptEntries([], readToolPrompts(setToolPrompt(saved, 'mcp__server__query', null))!)).toEqual([])
  })

  it('retains source defaults separately from overrides', () => {
    const catalog = [{ name: 'read_file', defaults: [{ source: 'file_read_tools', description: 'Original' }] }]
    const entries = toolPromptEntries(catalog, { read_file: 'Custom', plugin_tool: 'Plugin instructions' })
    expect(entries.find(item => item.name === 'read_file')?.defaults[0]?.description).toBe('Original')
    expect(entries).toHaveLength(2)
  })

  it('rejects malformed data and does not mutate the source document', () => {
    for (const tool_prompts of [null, [], { read_file: false }, { 'bad name': 'text' }, { read_file: 'x'.repeat(32001) }]) {
      expect(readToolPrompts({ tool_prompts })).toBeNull()
    }
    const data = { tool_prompts: { read_file: 'original' } }
    expect(() => setToolPrompt(data, 'read_file', 'x'.repeat(32001))).toThrow()
    expect(data.tool_prompts.read_file).toBe('original')
    const special = setToolPrompt({}, '__proto__', 'valid tool name')
    expect(Object.hasOwn(readToolPrompts(special)!, '__proto__')).toBe(true)
  })
})
