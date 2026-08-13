import { describe, expect, it } from 'vitest'
import {
  NODE_CARD_MAX_HEIGHT,
  NODE_CARD_MAX_WIDTH,
  NODE_CARD_MIN_HEIGHT,
  NODE_CARD_MIN_WIDTH,
} from '../src/components/agent-board/boardModel'
import { edgeResizeSize } from '../src/components/agent-board/edgeResize'

describe('node resize', () => {
  it('can shrink a node below the default card dimensions', () => {
    expect(edgeResizeSize(
      { handle: 'bottom-right', startWidth: 230, startHeight: 250 },
      { dx: -206, dy: -234 },
      {
        minWidth: NODE_CARD_MIN_WIDTH,
        maxWidth: NODE_CARD_MAX_WIDTH,
        minHeight: NODE_CARD_MIN_HEIGHT,
        maxHeight: NODE_CARD_MAX_HEIGHT,
      },
    )).toEqual({ width: 24, height: 16 })
  })
})
