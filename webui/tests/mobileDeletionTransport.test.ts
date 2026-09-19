import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { deleteMobileNodeMessage, deleteMobileNodeMessages, deleteMobileNodeTurn } from '../src/api'

const fetchMock = vi.fn()
beforeEach(() => {
  vi.stubGlobal('window', { location: { pathname: `/board/${'a'.repeat(64)}`, origin: 'https://cloud.example' } })
  vi.stubGlobal('document', { querySelector: () => ({}) })
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset().mockImplementation(async () => Response.json({ ok: true, deleted: 1, undo_token: 'undo-1' }))
})
afterEach(() => vi.unstubAllGlobals())

describe('mobile memory deletion through the shared Board API', () => {
  it('preserves node, graph, message IDs and undo token over the P2P-compatible endpoint', async () => {
    const result = await deleteMobileNodeMessages('local', 'graph / 1', 'agent / 1', ['m1', 'm2'])
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/nodes/instances/agent%20%2F%201/memory/messages/delete?graph_id=graph%20%2F%201',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ message_ids: ['m1', 'm2'] }) }),
    )
    expect(result.undo_token).toBe('undo-1')
  })
  it('supports a single message and a complete turn through the same desktop operations', async () => {
    await deleteMobileNodeMessage('local', 'g', 'n', 'm')
    expect(fetchMock).toHaveBeenLastCalledWith('/api/nodes/instances/n/memory/messages/m?graph_id=g', expect.objectContaining({ method: 'DELETE' }))
    await deleteMobileNodeTurn('local', 'g', 'n', 'm')
    expect(fetchMock).toHaveBeenLastCalledWith('/api/nodes/instances/n/memory/turns/delete?graph_id=g', expect.objectContaining({ body: JSON.stringify({ user_message_id: 'm' }) }))
  })
  it('rejects a different PC rather than deleting on the current device', async () => {
    await expect(deleteMobileNodeMessages('other', 'g', 'n', ['m'])).rejects.toThrow('current device')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
