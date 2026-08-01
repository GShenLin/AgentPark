import { describe, expect, it } from 'vitest'
import {
  boardPointToGridPosition,
  findAvailableGridOrigin,
  gridRectangleCellKeys,
  normalizeBoardLayoutDefaults,
  occupiedGridCellKeys,
} from '../src/components/agent-board/boardGrid'

const grid = { cellWidth: 300, cellHeight: 320 }

describe('board grid', () => {
  it('normalizes workspace board layout defaults', () => {
    expect(normalizeBoardLayoutDefaults({
      boardLayout: {
        gridCellWidth: 400,
        gridCellHeight: 500,
        nodeWidth: 320,
        nodeHeight: 360,
      },
    })).toEqual({ cellWidth: 400, cellHeight: 500, nodeWidth: 320, nodeHeight: 360 })
  })

  it('snaps a canvas point to the nearest grid origin', () => {
    expect(boardPointToGridPosition({ x: 449, y: 481 }, grid)).toEqual({ grid_x: 1, grid_y: 2 })
    expect(boardPointToGridPosition({ x: 451, y: 479 }, grid)).toEqual({ grid_x: 2, grid_y: 1 })
  })

  it('marks every cell covered by a large node', () => {
    const occupied = occupiedGridCellKeys(
      [{ id: 'wide', ui: { grid_x: 2, grid_y: 3, width: 601, height: 641 } }],
      grid,
    )
    expect(occupied).toEqual(gridRectangleCellKeys({ grid_x: 2, grid_y: 3 }, 3, 3))
  })

  it('finds a nearest origin whose whole rectangle is free', () => {
    const occupied = gridRectangleCellKeys({ grid_x: 1, grid_y: 1 }, 2, 2)
    const result = findAvailableGridOrigin(occupied, { width: 601, height: 321 }, grid, { grid_x: 1, grid_y: 1 })
    const resultCells = gridRectangleCellKeys(result, 3, 2)
    expect(Array.from(resultCells).some((key) => occupied.has(key))).toBe(false)
  })
})
