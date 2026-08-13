import { describe, expect, it } from 'vitest'
import {
  isLatestMemoryTurn,
  shouldLoadPreviousTurnsOnCollapse,
} from '../src/components/memoryTurnHistoryPolicy'

const entries = [
  { type: 'message' as const },
  { type: 'turn' as const },
  { type: 'message' as const },
  { type: 'turn' as const },
]

describe('memory turn history loading policy', () => {
  it('identifies the last turn even when other feed entries surround turns', () => {
    expect(isLatestMemoryTurn(entries, 1)).toBe(false)
    expect(isLatestMemoryTurn(entries, 3)).toBe(true)
  })

  it('loads previous turns only when the latest turn is collapsed with partial history', () => {
    expect(shouldLoadPreviousTurnsOnCollapse(entries, 3, false, false)).toBe(true)
    expect(shouldLoadPreviousTurnsOnCollapse(entries, 3, true, false)).toBe(false)
    expect(shouldLoadPreviousTurnsOnCollapse(entries, 3, false, true)).toBe(false)
    expect(shouldLoadPreviousTurnsOnCollapse(entries, 1, false, false)).toBe(false)
  })
})
