import { appEventsStreamUrl } from '../api'
import { measureNodeOpenWork } from '../nodeOpenDiagnostics'
import { resolveStreamSnapshotTransition } from '../eventStreamProtocol'
import { notifyUserInteractionGraphEvent } from './useUserInteractions'
import { notifyWorkAlertGraphEvent } from './useWorkAlerts'

let source: EventSource | null = null
let consumers = 0
let lastGlobalVersion = 0
let receivedStreamSnapshot = false
let resyncOnSnapshot = false
let lastStreamGapDispatchAt = 0
const listeners = new Set<(payload: Record<string, unknown>) => void>()
const STREAM_GAP_RESYNC_MIN_INTERVAL_MS = 2000

function dispatchAppEvent(payload: Record<string, unknown>) {
  for (const listener of listeners) measureNodeOpenWork('sse_listener', 0, () => listener(payload))
  notifyUserInteractionGraphEvent(payload)
  notifyWorkAlertGraphEvent(payload)
}

function dispatchStreamGap(payload: Record<string, unknown>, force = false) {
  const now = Date.now()
  if (!force && now - lastStreamGapDispatchAt < STREAM_GAP_RESYNC_MIN_INTERVAL_MS) return
  lastStreamGapDispatchAt = now
  dispatchAppEvent(payload)
}

function processAppEvent(payload: Record<string, unknown>) {
  const eventName = String(payload.event || '').trim()
  const globalVersion = Number(payload.global_version || 0)
  if (eventName === 'stream_snapshot') {
    const transition = resolveStreamSnapshotTransition(receivedStreamSnapshot, lastGlobalVersion, globalVersion)
    if (resyncOnSnapshot) dispatchStreamGap({ event: 'stream_gap', reason: 'connection_restored', global_version: globalVersion }, true)
    else if (transition.gap) dispatchStreamGap(transition.gap, transition.forceGap)
    resyncOnSnapshot = false
    receivedStreamSnapshot = true
    lastGlobalVersion = transition.nextGlobalVersion
    dispatchAppEvent(payload)
    return
  }
  if (eventName !== 'stream_gap' && lastGlobalVersion > 0 && globalVersion > lastGlobalVersion + 1) {
    dispatchStreamGap({
      event: 'stream_gap',
      from_global_version: lastGlobalVersion + 1,
      to_global_version: globalVersion - 1,
      global_version: globalVersion - 1,
    })
  }
  if (globalVersion > 0) lastGlobalVersion = Math.max(lastGlobalVersion, globalVersion)
  if (eventName === 'stream_gap') dispatchStreamGap(payload)
  else dispatchAppEvent(payload)
}

export function subscribeAppEvents(listener: (payload: Record<string, unknown>) => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function startAppEventStream(options: { resync?: boolean } = {}) {
  resyncOnSnapshot = resyncOnSnapshot || !!options.resync
  consumers += 1
  if (!source) {
    source = new EventSource(appEventsStreamUrl())
    const activeSource = source
    source.onmessage = (event) => {
      if (source !== activeSource) return
      try {
        const raw = String(event.data || '{}')
        const payload = measureNodeOpenWork('sse_parse', raw.length, () => JSON.parse(raw)) as Record<string, unknown>
        measureNodeOpenWork('sse_dispatch', raw.length, () => processAppEvent(payload))
      } catch (error) {
        console.error('Failed to process app event stream payload.', error)
      }
    }
    source.onerror = (event) => {
      console.error('App event stream connection failed.', event)
    }
  }
  return () => {
    consumers = Math.max(0, consumers - 1)
    if (consumers || !source) return
    source.close()
    source = null
    lastGlobalVersion = 0
    receivedStreamSnapshot = false
    resyncOnSnapshot = false
    lastStreamGapDispatchAt = 0
  }
}
