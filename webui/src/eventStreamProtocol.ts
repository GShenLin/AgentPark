export type LiveStreamFrame = {
  version: number
  baseVersion: number
  streamType: string
}

export type LiveStreamFrameDecision = {
  status: 'accept' | 'stale' | 'gap'
  frame: LiveStreamFrame
}

export function classifyLiveStreamFrame(
  payload: Record<string, unknown>,
  currentVersion: number,
): LiveStreamFrameDecision {
  const version = Number(payload.version || 0)
  const baseVersion = Number(payload.base_version ?? version - 1)
  const streamType = String(payload.stream_type || 'snapshot').trim().toLowerCase()
  const frame = { version, baseVersion, streamType }
  if (version <= currentVersion) return { status: 'stale', frame }
  if (streamType === 'delta' && baseVersion !== currentVersion) return { status: 'gap', frame }
  return { status: 'accept', frame }
}

export function reconcileLiveStreamVersion(currentVersion: number, snapshotVersion: unknown): number {
  return Math.max(currentVersion, Number(snapshotVersion || 0))
}

export type StreamSnapshotTransition = {
  nextGlobalVersion: number
  gap: Record<string, unknown> | null
  forceGap: boolean
}

export function resolveStreamSnapshotTransition(
  receivedSnapshot: boolean,
  lastGlobalVersion: number,
  snapshotGlobalVersion: number,
): StreamSnapshotTransition {
  if (!receivedSnapshot) {
    return { nextGlobalVersion: snapshotGlobalVersion, gap: null, forceGap: false }
  }
  if (snapshotGlobalVersion < lastGlobalVersion) {
    return {
      nextGlobalVersion: snapshotGlobalVersion,
      gap: {
        event: 'stream_gap',
        reason: 'stream_epoch_reset',
        previous_global_version: lastGlobalVersion,
        global_version: snapshotGlobalVersion,
      },
      forceGap: true,
    }
  }
  if (snapshotGlobalVersion > lastGlobalVersion) {
    return {
      nextGlobalVersion: snapshotGlobalVersion,
      gap: {
        event: 'stream_gap',
        from_global_version: lastGlobalVersion + 1,
        to_global_version: snapshotGlobalVersion,
        global_version: snapshotGlobalVersion,
      },
      forceGap: false,
    }
  }
  return { nextGlobalVersion: lastGlobalVersion, gap: null, forceGap: false }
}
