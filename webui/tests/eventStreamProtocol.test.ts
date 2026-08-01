import { describe, expect, it } from 'vitest'
import {
  classifyLiveStreamFrame,
  reconcileLiveStreamVersion,
  resolveStreamSnapshotTransition,
} from '../src/eventStreamProtocol'

describe('event stream protocol', () => {
  it('accepts a coalesced delta when its base version matches the consumer cursor', () => {
    const decision = classifyLiveStreamFrame({
      version: 3,
      base_version: 1,
      stream_type: 'delta',
      live_delta: 'bc',
    }, 1)

    expect(decision.status).toBe('accept')
    expect(decision.frame).toEqual({ version: 3, baseVersion: 1, streamType: 'delta' })
  })

  it('requires resync when a delta is based on a different consumer cursor', () => {
    expect(classifyLiveStreamFrame({
      version: 8,
      base_version: 6,
      stream_type: 'delta',
    }, 5).status).toBe('gap')
  })

  it('does not let an older HTTP snapshot move an active live cursor backwards', () => {
    expect(reconcileLiveStreamVersion(5, 3)).toBe(5)
    expect(reconcileLiveStreamVersion(5, 8)).toBe(8)
  })

  it('recognizes a lower reconnect snapshot as a new server epoch', () => {
    const transition = resolveStreamSnapshotTransition(true, 41, 0)

    expect(transition.nextGlobalVersion).toBe(0)
    expect(transition.forceGap).toBe(true)
    expect(transition.gap).toMatchObject({
      event: 'stream_gap',
      reason: 'stream_epoch_reset',
      previous_global_version: 41,
      global_version: 0,
    })
  })

  it('keeps the normal reconnect gap contract within one server epoch', () => {
    const transition = resolveStreamSnapshotTransition(true, 10, 13)

    expect(transition.nextGlobalVersion).toBe(13)
    expect(transition.forceGap).toBe(false)
    expect(transition.gap).toMatchObject({
      event: 'stream_gap',
      from_global_version: 11,
      to_global_version: 13,
    })
  })
})
