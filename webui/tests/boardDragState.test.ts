import { describe, expect, it } from 'vitest'
import { didBoardItemsChangeGridPosition, type BoardPosition } from '../src/components/agent-board/boardDragState'

function changed(startPositions: Record<string, BoardPosition>, currentPositions: Record<string, BoardPosition>) {
  return didBoardItemsChangeGridPosition({
    itemIds: Object.keys(startPositions),
    startPositions,
    getPosition: (itemId) => currentPositions[itemId] || null,
  })
}

describe('didBoardItemsChangeGridPosition', () => {
  it('does not treat pointer movement within the same grid cell as a node move', () => {
    expect(changed({ node: { grid_x: 2, grid_y: 3 } }, { node: { grid_x: 2, grid_y: 3 } })).toBe(false)
  })

  it('detects a grid-cell change in any node of a moved selection', () => {
    expect(changed(
      { a: { grid_x: 1, grid_y: 1 }, b: { grid_x: 2, grid_y: 1 } },
      { a: { grid_x: 1, grid_y: 1 }, b: { grid_x: 3, grid_y: 1 } },
    )).toBe(true)
  })
})
