import { describe, expect, it } from 'vitest'
import { buildBoardPastePlan, type BoardClipboardSnapshot } from '../src/components/agent-board/boardClipboard'
import type { NodeCard } from '../src/components/agent-board/context'

function node(id: string, grid_x: number, grid_y: number, width?: number, height?: number): NodeCard {
  return {
    id,
    name: id,
    typeId: 'agent_node',
    inputNum: 1,
    outputNum: 1,
    ui: { grid_x, grid_y, ...(width == null ? {} : { width }), ...(height == null ? {} : { height }) },
    last_message: null,
    lastRuntimeEvent: null,
    runtimeEvents: [],
  }
}

function build(snapshot: BoardClipboardSnapshot, anchor?: { grid_x: number; grid_y: number }, occupied = new Set<string>()) {
  let nextId = 0
  return buildBoardPastePlan({
    snapshot,
    offset: 1,
    anchor,
    occupied,
    grid: { cellWidth: 300, cellHeight: 320 },
    makeUniqueId: () => `copy-${++nextId}`,
    makeLinkId: () => 'new-link',
  })
}

describe('buildBoardPastePlan', () => {
  it('places a copied node at the mouse anchor', () => {
    const plan = build({ graphId: 'default', nodes: [node('a', 1, 1)], links: [] }, { grid_x: 4, grid_y: 3 })

    expect(plan.nodes[0]?.ui).toMatchObject({ grid_x: 4, grid_y: 3 })
  })

  it('moves a multi-node selection to the mouse while preserving its relative layout', () => {
    const plan = build(
      {
        graphId: 'default',
        nodes: [node('a', 1, 1), node('b', 2, 2)],
        links: [{ id: 'link-a-b', from: { node: 'a', index: 0 }, to: { node: 'b', index: 0 } }],
      },
      { grid_x: 5, grid_y: 4 },
    )

    expect(plan.nodes.map((item) => item.ui)).toEqual([
      { grid_x: 5, grid_y: 4 },
      { grid_x: 6, grid_y: 5 },
    ])
    expect(plan.links).toEqual([
      { id: 'new-link', from: { node: 'copy-1', index: 0 }, to: { node: 'copy-2', index: 0 } },
    ])
  })

  it('keeps the staggered fallback when the mouse is outside the board', () => {
    const plan = build({ graphId: 'default', nodes: [node('a', 1, 1)], links: [] })

    expect(plan.nodes[0]?.ui).toMatchObject({ grid_x: 2, grid_y: 2 })
  })

  it('moves a large pasted node away when any occupied cell intersects its rectangle', () => {
    const plan = build(
      { graphId: 'default', nodes: [node('a', 0, 0, 601, 321)], links: [] },
      { grid_x: 1, grid_y: 1 },
      new Set(['2:2']),
    )

    expect(plan.nodes[0]?.ui).not.toMatchObject({ grid_x: 1, grid_y: 1 })
  })
})
