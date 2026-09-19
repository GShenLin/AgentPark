import { createBrowserUuid } from './utils/browserId'
import { addFrameAttribution, diagnosticSourceUrl, type AttributionReport, type FrameTiming } from './nodeOpenAttribution'

type Stage = 'selection' | 'selection_watch' | 'board_selection_flush' | 'board_focus' | 'memory_shown' | 'request_start' | 'response_headers' |
  'response_json' | 'request_failed' | 'memory_applied' | 'live_applied' | 'vue_flush' |
  'frame_after_update' | 'scroll_layout' | 'longtask' | 'long_animation_frame' | 'capture_end'
type Metrics = Record<string, number>
type Measurement = { stage: Stage; at_ms: number; metrics: Metrics; endpoint: string; request_id: string }
export type NodeOpenTrace = {
  trace_id: string; graph_id: string; node_id: string; started_at: string; events: Measurement[]
}
type Capture = { payload: NodeOpenTrace; attribution: AttributionReport; start: number; closed: boolean; dropped: number; observers: PerformanceObserver[]; timer: number }
let current: Capture | null = null
let transport: ((trace: NodeOpenTrace, attribution: AttributionReport) => Promise<unknown>) | null = null

export function setNodeOpenTraceTransport(send: (trace: NodeOpenTrace, attribution: AttributionReport) => Promise<unknown>) {
  transport = send
}

function record(capture: Capture, stage: Stage, metrics: Metrics = {}, endpoint = '', requestId = '', at = performance.now()) {
  if (capture.closed) return
  if (capture.payload.events.length >= 499 && stage !== 'capture_end') {
    capture.dropped += 1
    return
  }
  capture.payload.events.push({ stage, at_ms: at - capture.start, metrics, endpoint, request_id: requestId })
}

function observe(capture: Capture, type: 'longtask' | 'long-animation-frame') {
  if (typeof PerformanceObserver === 'undefined' || !PerformanceObserver.supportedEntryTypes.includes(type)) return
  const consume = (entries: PerformanceEntry[]) => {
    for (const entry of entries) {
      if (entry.startTime < capture.start) continue
      if (type === 'longtask') {
        record(capture, 'longtask', { duration_ms: entry.duration }, '', '', entry.startTime)
      } else {
        const frame = entry as FrameTiming
        addFrameAttribution(capture.attribution, frame, capture.start)
        record(capture, 'long_animation_frame', {
          duration_ms: frame.duration, blocking_ms: frame.blockingDuration,
          render_ms: frame.renderStart > 0 ? frame.startTime + frame.duration - frame.renderStart : 0,
          style_layout_to_frame_end_ms: frame.styleAndLayoutStart > 0 ? frame.startTime + frame.duration - frame.styleAndLayoutStart : 0,
          forced_layout_ms: frame.scripts.reduce((sum, script) => sum + script.forcedStyleAndLayoutDuration, 0),
          script_count: frame.scripts.length,
          attributed_script_ms: frame.scripts.reduce((sum, script) => sum + script.duration, 0),
        }, '', '', frame.startTime)
      }
    }
  }
  const observer = new PerformanceObserver(list => consume(list.getEntries()))
  observer.observe({ type })
  // Drain queued entries before closing so the final long frame is retained.
  drains.set(observer, () => consume(observer.takeRecords()))
  capture.observers.push(observer)
}
const drains = new Map<PerformanceObserver, () => void>()

function finish(capture: Capture, switched: boolean) {
  if (capture.closed) return
  window.clearTimeout(capture.timer)
  for (const observer of capture.observers) {
    drains.get(observer)?.()
    observer.disconnect()
    drains.delete(observer)
  }
  record(capture, 'capture_end', { switched: Number(switched), dropped_events: capture.dropped, visible: Number(document.visibilityState === 'visible') })
  capture.closed = true
  console.info('[NodeOpenPerformance]', capture.payload, capture.attribution)
  if (!transport) {
    console.error('[NodeOpenPerformance] log transport is not configured')
    return
  }
  void transport(capture.payload, capture.attribution).catch(error => console.error('[NodeOpenPerformance] failed to save trace', error))
}

export function beginNodeOpenTrace(graphId: string, nodeId: string) {
  if (current && !current.closed) finish(current, true)
  const payload: NodeOpenTrace = { trace_id: createBrowserUuid(), graph_id: graphId, node_id: nodeId, started_at: new Date().toISOString(), events: [] }
  const capture: Capture = {
    payload,
    attribution: {
      schema_version: 1, trace_id: payload.trace_id, graph_id: graphId, node_id: nodeId,
      started_at: payload.started_at,
      assets: Array.from(document.scripts).map(script => diagnosticSourceUrl(script.src)).filter(Boolean),
      frames: [], app_work: [], dropped_frames: 0, dropped_scripts: 0, dropped_app_work: 0,
    },
    start: performance.now(), closed: false, dropped: 0, observers: [], timer: 0,
  }
  current = capture
  record(capture, 'selection', {
    visible: Number(document.visibilityState === 'visible'),
    longtask_supported: Number(typeof PerformanceObserver !== 'undefined' && PerformanceObserver.supportedEntryTypes.includes('longtask')),
    long_frame_supported: Number(typeof PerformanceObserver !== 'undefined' && PerformanceObserver.supportedEntryTypes.includes('long-animation-frame')),
  })
  observe(capture, 'longtask')
  observe(capture, 'long-animation-frame')
  capture.timer = window.setTimeout(() => finish(capture, false), 10000)
}

export function nodeOpenMarker(graphId: string, nodeId: string) {
  const capture = current
  if (!capture || capture.closed || capture.payload.graph_id !== graphId || capture.payload.node_id !== nodeId) return null
  return (stage: Stage, metrics: Metrics = {}) => record(capture, stage, metrics)
}

export function traceNodeOpenRequest(path: string) {
  const capture = current
  if (!capture || capture.closed || path.includes('/open-diagnostics')) return null
  const endpoint = path.split('?')[0]!
  if (!endpoint.startsWith('/api/')) return null
  const requestId = createBrowserUuid()
  record(capture, 'request_start', {}, endpoint, requestId)
  const start = performance.now()
  return {
    traceId: capture.payload.trace_id, requestId,
    mark(stage: 'response_headers' | 'response_json' | 'request_failed', metrics: Metrics = {}) {
      record(capture, stage, { elapsed_ms: performance.now() - start, ...metrics }, endpoint, requestId)
    },
  }
}

export function measureNodeOpenWork<T>(name: 'sse_parse' | 'sse_dispatch' | 'sse_listener', inputChars: number, work: () => T): T {
  const capture = current
  if (!capture || capture.closed) return work()
  const start = performance.now()
  try {
    return work()
  } finally {
    if (capture.attribution.app_work.length < 500) {
      capture.attribution.app_work.push({ name, at_ms: start - capture.start, duration_ms: performance.now() - start, input_chars: inputChars })
    } else {
      capture.attribution.dropped_app_work += 1
    }
  }
}
