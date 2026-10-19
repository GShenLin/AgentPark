import { beforeEach, afterEach, expect, it, vi } from 'vitest'

beforeEach(() => {
  vi.resetModules()
  const data = new Map<string, string>()
  vi.stubGlobal('window', {
    localStorage: {
      get length() { return data.size }, key: (i: number) => [...data.keys()][i] ?? null,
      getItem: (key: string) => data.get(key) ?? null,
      setItem: (key: string, value: string) => data.set(key, value),
      removeItem: (key: string) => data.delete(key),
    },
    addEventListener: vi.fn(), matchMedia: () => ({ matches: false }),
  })
})
afterEach(() => vi.unstubAllGlobals())

it('lights only for persisted work, deduplicates repeats, and excludes snapshots/progress', async () => {
  const { notifyWorkAlertGraphEvent } = await import('../src/composables/useWorkAlerts')
  const state = (await import('../src/composables/useNodeUnread')).useNodeUnread()
  const event = { event: 'work_persisted_alert', graph_id: 'g', node_id: 'n', alert_id: 'receipt-1' }
  notifyWorkAlertGraphEvent({ ...event, event: 'node_progress_updated' })
  notifyWorkAlertGraphEvent({ ...event, stream_snapshot: true })
  expect(state.receipt('g', 'n')).toBe('')
  notifyWorkAlertGraphEvent(event)
  expect(state.receipt('g', 'n')).toBe('receipt-1')
  state.acknowledge('g', 'n', 'receipt-1')
  notifyWorkAlertGraphEvent(event)
  expect(state.receipt('g', 'n')).toBe('')
})

it('keeps a newer message unread when acknowledging an older load and isolates graph identity', async () => {
  const { recordNodeUnread, useNodeUnread } = await import('../src/composables/useNodeUnread')
  const state = useNodeUnread()
  recordNodeUnread('g', 'n', 'old')
  recordNodeUnread('other', 'n', 'other-receipt')
  recordNodeUnread('g', 'n', 'new')
  state.acknowledge('g', 'n', 'old')
  expect(state.receipt('g', 'n')).toBe('new')
  state.acknowledge('g', 'n', 'new')
  expect(state.receipt('other', 'n')).toBe('other-receipt')
})

it('restores unread markers after a window is reopened', async () => {
  const first = await import('../src/composables/useNodeUnread')
  first.recordNodeUnread('图', '节点', 'saved')
  vi.resetModules()
  const restored = (await import('../src/composables/useNodeUnread')).useNodeUnread()
  expect(restored.receipt('图', '节点')).toBe('saved')
})
