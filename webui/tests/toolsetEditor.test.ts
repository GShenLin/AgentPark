import { describe, expect, it } from 'vitest'
import { readToolsets, toggleTool, validToolsetId } from '../src/toolsetEditor'

describe('toolset editing', () => {
  it('preserves description and order, prevents duplicate tools, and supports an empty set', () => {
    const set = { description: 'Read only', tools: ['file_read_tools:read_file'] }
    expect(toggleTool(set, set.tools[0]!, true)).toEqual(set)
    expect(toggleTool(set, 'image_tools:view_image', true).tools).toEqual([...set.tools, 'image_tools:view_image'])
    expect(toggleTool(set, set.tools[0]!, false)).toEqual({ description: 'Read only', tools: [] })
    expect(set.tools).toHaveLength(1)
  })
  it('rejects duplicate and invalid identifiers', () => {
    const sets = { system_tools: { description: '', tools: [] } }
    for (const id of ['system_tools', '9tools', '../tools', 'my tools', '']) expect(validToolsetId(id, sets)).toBe(false)
    expect(validToolsetId('my_tools', sets)).toBe(true)
  })
  it('rejects malformed documents when switching out of JSON mode', () => {
    for (const data of [{}, { toolsets: [] }, { toolsets: { demo: {} } }, { toolsets: { demo: { description: '', tools: [null] } } }]) {
      expect(readToolsets(data)).toBeNull()
    }
    expect(readToolsets({ toolsets: { demo: { description: '', tools: [] } } })).toEqual({ demo: { description: '', tools: [] } })
  })
})
