import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  beginNodeOpenTrace, measureNodeOpenWork, nodeOpenMarker, setNodeOpenTraceTransport, traceNodeOpenRequest, type NodeOpenTrace,
} from '../src/nodeOpenDiagnostics'
import type { AttributionReport } from '../src/nodeOpenAttribution'

afterEach(() => {
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function setup() {
  vi.useFakeTimers()
  vi.stubGlobal('window', { setTimeout, clearTimeout })
  vi.stubGlobal('document', { visibilityState: 'visible', scripts: [] })
  vi.stubGlobal('PerformanceObserver', undefined)
  vi.spyOn(console, 'info').mockImplementation(() => {})
  const send = vi.fn(async (_trace: NodeOpenTrace, _attribution: AttributionReport) => ({ ok: true }))
  setNodeOpenTraceTransport(send)
  return send
}

describe('node open diagnostic capture', () => {
  it('measures app work without replacing its value or swallowing its error', () => {
    const send = setup()
    beginNodeOpenTrace('XYJ', 'Package1')
    expect(measureNodeOpenWork('sse_parse', 10, () => 42)).toBe(42)
    const error = new Error('original failure')
    expect(() => measureNodeOpenWork('sse_dispatch', 10, () => { throw error })).toThrow(error)
    vi.advanceTimersByTime(10000)
    const attribution = send.mock.calls[0]![1]
    expect(attribution.trace_id).toBe(send.mock.calls[0]![0].trace_id)
    expect(attribution.app_work.map(work => work.name)).toEqual(['sse_parse', 'sse_dispatch'])
  })
  it('correlates requests and measurements and saves after the capture window', () => {
    const send = setup()
    beginNodeOpenTrace('XYJ', 'Package1')
    const request = traceNodeOpenRequest('/api/nodes/instances/Package1/memory?graph_id=XYJ')!
    request.mark('response_headers', { status: 200 })
    request.mark('response_json', { body_and_json_ms: 3 })
    nodeOpenMarker('XYJ', 'Package1')!('scroll_layout', { height_read_ms: 85 })
    expect(traceNodeOpenRequest('/api/nodes/instances/Package1/open-diagnostics')).toBeNull()
    expect(send).not.toHaveBeenCalled()
    vi.advanceTimersByTime(10000)
    const trace = send.mock.calls[0]![0]
    expect(trace.trace_id).toBe(request.traceId)
    expect(trace.events.find((event: {stage: string}) => event.stage === 'response_json')?.request_id).toBe(request.requestId)
    expect(trace.events.at(-1)?.stage).toBe('capture_end')
    expect(JSON.stringify(trace)).not.toContain('?graph_id')
    expect(nodeOpenMarker('XYJ', 'Package1')).toBeNull()
  })

  it('keeps a stale response from being attributed to the next node', () => {
    const send = setup()
    beginNodeOpenTrace('XYJ', 'Package1')
    const request = traceNodeOpenRequest('/api/sample')!
    const mark = nodeOpenMarker('XYJ', 'Package1')!
    beginNodeOpenTrace('XYJ', 'Build1')
    request.mark('response_json', { body_and_json_ms: 99 })
    mark('scroll_layout', { height_read_ms: 99 })
    vi.advanceTimersByTime(10000)
    expect(send).toHaveBeenCalledTimes(2)
    expect(send.mock.calls[0]![0].events.at(-1)?.metrics.switched).toBe(1)
    expect(send.mock.calls[1]![0].node_id).toBe('Build1')
    expect(send.mock.calls[1]![0].events.some((event: {stage: string}) => event.stage === 'response_json')).toBe(false)
  })
})
