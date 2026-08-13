import { describe, expect, it } from 'vitest'
import { resolveNodeMoveIds } from '../src/components/agent-board/boardSelection'

describe('resolveNodeMoveIds', () => {
  it('moves only the pressed node when it is not selected yet', () => {
    expect(resolveNodeMoveIds(['selected-a', 'selected-b'], 'pressed')).toEqual(['pressed'])
  })

  it('moves the full selection when the pressed node is already selected', () => {
    expect(resolveNodeMoveIds(['selected-a', 'selected-b'], 'selected-b')).toEqual(['selected-a', 'selected-b'])
  })
})
