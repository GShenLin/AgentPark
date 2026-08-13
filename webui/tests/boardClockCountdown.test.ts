import { describe, expect, it } from 'vitest'
import {
  boardClockRemainingSeconds,
  formatBoardClockCountdown,
} from '../src/components/agent-board/boardClockCountdown'

describe('board clock countdown', () => {
  it('derives the remaining whole seconds from the server-owned fire time', () => {
    expect(boardClockRemainingSeconds(100, 95_000)).toBe(5)
    expect(boardClockRemainingSeconds('100', 95_001)).toBe(5)
    expect(boardClockRemainingSeconds(100, 99_999)).toBe(1)
  })

  it('clamps an elapsed clock at zero', () => {
    expect(boardClockRemainingSeconds(100, 100_000)).toBe(0)
    expect(boardClockRemainingSeconds(100, 101_000)).toBe(0)
  })

  it('uses the persisted message only when the fire time is unavailable', () => {
    expect(formatBoardClockCountdown(100, 95_000, 'Working')).toBe('Working: 5s')
    expect(formatBoardClockCountdown(null, 95_000, 'Working')).toBe('Working')
    expect(formatBoardClockCountdown('invalid', 95_000, 'Working')).toBe('Working')
  })
})
