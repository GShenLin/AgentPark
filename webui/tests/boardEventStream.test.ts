import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('../src/api', () => ({ appEventsStreamUrl: () => '/api/events' }))
vi.mock('../src/composables/useUserInteractions', () => ({ notifyUserInteractionGraphEvent: vi.fn() }))
vi.mock('../src/composables/useWorkAlerts', () => ({ notifyWorkAlertGraphEvent: vi.fn() }))
import { startAppEventStream, subscribeAppEvents } from '../src/composables/useAppEventStream'

const sources: FakeSource[] = []
class FakeSource {
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: ((event: unknown) => void) | null = null
  close = vi.fn()
  constructor() { sources.push(this) }
  snapshot(version: number) { this.onmessage?.({ data: JSON.stringify({ event: 'stream_snapshot', global_version: version }) }) }
}
afterEach(() => { vi.unstubAllGlobals(); sources.splice(0) })

describe('Board event subscription replacement', () => {
  it('closes the old stream, ignores its late events and resyncs the new stream boundary', () => {
    vi.stubGlobal('EventSource', FakeSource)
    const events: Record<string, unknown>[] = []
    const unsubscribe = subscribeAppEvents(event => events.push(event))
    const stopOld = startAppEventStream()
    sources[0]!.snapshot(10)
    stopOld()
    expect(sources[0]!.close).toHaveBeenCalledOnce()
    const stopNew = startAppEventStream({ resync: true })
    sources[0]!.snapshot(999)
    expect(events).toHaveLength(1)
    sources[1]!.snapshot(10)
    expect(events[1]).toMatchObject({ event: 'stream_gap', reason: 'connection_restored' })
    expect(events[2]).toMatchObject({ event: 'stream_snapshot', global_version: 10 })
    sources[1]!.snapshot(10)
    expect(events.filter(event => event.event === 'stream_gap')).toHaveLength(1)
    stopNew()
    unsubscribe()
  })
})
