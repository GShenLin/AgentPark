import { appEventsStreamUrl } from '../api'
import { notifyUserInteractionGraphEvent } from './useUserInteractions'
import { notifyWorkAlertGraphEvent } from './useWorkAlerts'

let source: EventSource | null = null
let consumers = 0
let lastGlobalVersion = 0
let receivedStreamSnapshot = false
let lastStreamGapDispatchAt = 0
const listeners = new Set<(payload: Record<string, unknown>) => void>()
const STREAM_GAP_RESYNC_MIN_INTERVAL_MS = 2000

function dispatchAppEvent(payload: Record<string, unknown>) {
  for (const listener of listeners) listener(payload)
  notifyUserInteractionGraphEvent(payload)
  notifyWorkAlertGraphEvent(payload)
}

function dispatchStreamGap(payload: Record<string, unknown>) {
  const now = Date.now()
  if (now - lastStreamGapDispatchAt < STREAM_GAP_RESYNC_MIN_INTERVAL_MS) return
  lastStreamGapDispatchAt = now
  dispatchAppEvent(payload)
}

function processAppEvent(payload: Record<string, unknown>) {
  const eventName = String(payload.event || '').trim()
  const globalVersion = Number(payload.global_version || 0)
  if (eventName === 'stream_snapshot') {
    if (receivedStreamSnapshot && globalVersion > lastGlobalVersion) {
      dispatchStreamGap({
        event: 'stream_gap',
        from_global_version: lastGlobalVersion + 1,
        to_global_version: globalVersion,
        global_version: globalVersion,
      })
    }
    receivedStreamSnapshot = true
    lastGlobalVersion = Math.max(lastGlobalVersion, globalVersion)
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

export function startAppEventStream() {
  consumers += 1
  if (!source) {
    source = new EventSource(appEventsStreamUrl())
    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(String(event.data || '{}')) as Record<string, unknown>
        processAppEvent(payload)
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
    lastStreamGapDispatchAt = 0
  }
}
