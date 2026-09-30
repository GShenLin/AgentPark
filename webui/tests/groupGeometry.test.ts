import { describe, expect, it } from 'vitest'
import { boundsOverlap, groupAtPoint, groupBounds, nodeCenter, selectionGroup, resizeGroupBounds } from '../src/groups/groupGeometry'
import type { AgentGroup } from '../src/groups/groupApi'
import type { NodeCard } from '../src/components/agent-board/context'

const grid = { cellWidth: 300, cellHeight: 320 }
function node(id: string, x: number, y: number, width = 230, height = 250): NodeCard {
  return { id, name: id, typeId: 'agent_node', inputNum: 1, outputNum: 1,
    ui: { grid_x: x, grid_y: y, width, height }, last_message: null }
}
function group(id: string, ids: string[], x = 0): AgentGroup {
  return { id, name: id, objective: '', bounds: { x, y: 0, width: 600, height: 500 },
    members: ids.map(node_id => ({ node_id, role: '' })), tasks: [], revision: 1, private: false,
    dissolved: false, created_at: '', updated_at: '' }
}

describe('group canvas membership', () => {
  it('encloses variable-size cards using the actual grid, including negative coordinates', () => {
    const members = [node('a', -1, 0, 280, 100), node('b', 2, 1, 400, 300)]
    const bounds = groupBounds(members, grid)
    expect(bounds.x).toBe(-300)
    expect(bounds.y).toBe(0)
    expect(bounds.x + bounds.width).toBe(1200)
    expect(bounds.y + bounds.height).toBe(640)
  })
  it('determines entering and leaving by the settled card center', () => {
    const team = group('team', ['a'])
    expect(groupAtPoint([team], nodeCenter(node('a', 1, 0), grid))?.id).toBe('team')
    expect(groupAtPoint([team], nodeCenter(node('a', 2, 0), grid))).toBeNull()
  })
  it('requires the exact membership selection for G dissolution', () => {
    const team = group('team', ['a', 'b'])
    expect(selectionGroup([team], ['b', 'a'])?.id).toBe('team')
    expect(selectionGroup([team], ['a'])).toBeNull()
    expect(selectionGroup([team], ['a', 'b', 'c'])).toBeNull()
  })
  it('rejects ambiguous overlapping frames rather than assigning arbitrarily', () => {
    expect(() => groupAtPoint([group('a', []), group('b', [], 300)], { x: 400, y: 100 })).toThrow('重叠')
    expect(boundsOverlap(group('a', []).bounds, group('b', [], 600).bounds)).toBe(false)
  })
})

it('snaps all resize directions and prevents inversion or negative coordinates', () => {
  const b = { x: 300, y: 320, width: 600, height: 640 }
  expect(resizeGroupBounds(b, 'se', 290, 310, grid)).toEqual({ x: 300, y: 320, width: 900, height: 960 })
  expect(resizeGroupBounds(b, 'nw', -999, -999, grid)).toEqual({ x: 0, y: 0, width: 900, height: 960 })
  expect(resizeGroupBounds(b, 'se', -999, -999, grid)).toEqual({ x: 300, y: 320, width: 300, height: 320 })
  expect(resizeGroupBounds(b, 'nw', 999, 999, grid)).toEqual({ x: 600, y: 640, width: 300, height: 320 })
})
it('assigns a shared boundary to only the cell on its right', () => {
  expect(groupAtPoint([group('a', []), group('b', [], 600)], {x: 600, y: 100})?.id).toBe('b')
})
