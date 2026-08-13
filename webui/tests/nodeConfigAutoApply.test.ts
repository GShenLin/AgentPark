import { describe, expect, it, vi } from 'vitest'
import {
  createNodeConfigAutoApplyQueue,
  type NodeConfigAutoApplyBatch,
} from '../src/components/agent-board/nodeConfigAutoApply'

describe('node config auto apply queue', () => {
  it('coalesces pending fields and preserves write order', async () => {
    const writes: NodeConfigAutoApplyBatch[] = []
    let releaseFirst: (() => void) | null = null
    const firstWrite = new Promise<void>((resolve) => {
      releaseFirst = resolve
    })
    const persist = vi.fn(async (batch: NodeConfigAutoApplyBatch) => {
      writes.push(batch)
      if (writes.length === 1) await firstWrite
    })
    const queue = createNodeConfigAutoApplyQueue({ persist, onError: vi.fn() })

    const initial = queue.enqueue('node-1', 'thinking', 'enabled')
    queue.enqueue('node-1', 'web_search', 'enabled')
    await Promise.resolve()
    queue.enqueue('node-1', 'thinking', 'disabled')
    releaseFirst?.()
    await initial

    expect(writes).toEqual([
      { nodeId: 'node-1', fields: { thinking: 'enabled', web_search: 'enabled' } },
      { nodeId: 'node-1', fields: { thinking: 'disabled' } },
    ])
  })

  it('reports a failed batch and continues with newer changes', async () => {
    const errors: NodeConfigAutoApplyBatch[] = []
    const persist = vi.fn()
      .mockRejectedValueOnce(new Error('save failed'))
      .mockResolvedValueOnce(undefined)
    const queue = createNodeConfigAutoApplyQueue({
      persist,
      onError: (_error, batch) => errors.push(batch),
    })

    const first = queue.enqueue('node-1', 'thinking', 'enabled')
    await Promise.resolve()
    queue.enqueue('node-1', 'thinking', 'disabled')
    await first

    expect(errors).toEqual([{ nodeId: 'node-1', fields: { thinking: 'enabled' } }])
    expect(persist).toHaveBeenCalledTimes(2)
  })
})
