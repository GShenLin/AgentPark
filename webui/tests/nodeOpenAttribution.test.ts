import { describe, expect, it } from 'vitest'
import { addFrameAttribution, diagnosticSourceUrl, type AttributionReport, type FrameTiming } from '../src/nodeOpenAttribution'

function report(): AttributionReport {
  return {
    schema_version: 1, trace_id: 'test', graph_id: 'XYJ', node_id: 'Package1', started_at: '', assets: [],
    frames: [], app_work: [], dropped_frames: 0, dropped_scripts: 0, dropped_app_work: 0,
  }
}

describe('native long-frame source evidence', () => {
  it('retains source position and execution costs without URL credentials or query data', () => {
    const output = report()
    addFrameAttribution(output, {
      startTime: 150, duration: 1400, scripts: [{
        startTime: 155, duration: 1390, executionStart: 156,
        forcedStyleAndLayoutDuration: 0.4, pauseDuration: 0,
        invoker: 'Window.requestAnimationFrame', invokerType: 'user-callback',
        sourceURL: 'https://user:password@example.test/assets/app.js?token=secret#fragment',
        sourceFunctionName: 'render', sourceCharPosition: 357, windowAttribution: 'self',
      }],
    } as FrameTiming, 100)
    expect(output.frames[0]?.at_ms).toBe(50)
    expect(output.frames[0]?.scripts[0]).toMatchObject({
      source_url: 'https://example.test/assets/app.js', function_name: 'render', char_position: 357,
      at_ms: 55, duration_ms: 1390, forced_layout_ms: 0.4,
    })
    expect(JSON.stringify(output)).not.toContain('secret')
    expect(diagnosticSourceUrl('data:text/javascript,private-code')).toBe('[data:]')
  })

  it('preserves unattributed frames instead of inventing a source', () => {
    const output = report()
    addFrameAttribution(output, { startTime: 150, duration: 1400, scripts: [] } as unknown as FrameTiming, 100)
    expect(output.frames[0]).toEqual({ at_ms: 50, duration_ms: 1400, script_count: 0, scripts: [] })
  })
})
