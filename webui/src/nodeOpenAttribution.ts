// Native source attribution is an entry point, not a sampled CPU call stack.
// Isolated-world extensions and cross-origin frames may have no attribution.
export type ScriptTiming = {
  startTime: number
  duration: number
  executionStart: number
  forcedStyleAndLayoutDuration: number
  pauseDuration: number
  invoker: string
  invokerType: string
  sourceURL: string
  sourceFunctionName: string
  sourceCharPosition: number
  windowAttribution: string
}

export type FrameTiming = PerformanceEntry & {
  blockingDuration: number
  renderStart: number
  styleAndLayoutStart: number
  scripts: ScriptTiming[]
}

export type AttributionReport = {
  schema_version: 1
  trace_id: string
  graph_id: string
  node_id: string
  started_at: string
  assets: string[]
  frames: Array<{
    at_ms: number
    duration_ms: number
    script_count: number
    scripts: Array<{
      at_ms: number; duration_ms: number; execution_start_ms: number
      forced_layout_ms: number; pause_ms: number
      invoker: string; invoker_type: string; source_url: string
      function_name: string; char_position: number; window_attribution: string
    }>
  }>
  app_work: Array<{ name: string; at_ms: number; duration_ms: number; input_chars: number }>
  dropped_frames: number
  dropped_scripts: number
  dropped_app_work: number
}

export function diagnosticSourceUrl(value: string): string {
  if (!value) return ''
  // Exclude inline data/blob content, URL credentials, queries and fragments.
  try {
    const url = new URL(value)
    if (!['http:', 'https:', 'chrome-extension:', 'file:'].includes(url.protocol)) return `[${url.protocol}]`
    url.username = ''
    url.password = ''
    url.search = ''
    url.hash = ''
    return url.href
  } catch {
    return '[unresolved source URL]'
  }
}

export function addFrameAttribution(report: AttributionReport, frame: FrameTiming, captureStart: number) {
  if (report.frames.length >= 100) {
    report.dropped_frames += 1
    return
  }
  report.dropped_scripts += Math.max(0, frame.scripts.length - 50)
  report.frames.push({
    at_ms: frame.startTime - captureStart, duration_ms: frame.duration,
    script_count: frame.scripts.length,
    scripts: frame.scripts.slice(0, 50).map(script => ({
      at_ms: script.startTime - captureStart, duration_ms: script.duration,
      execution_start_ms: script.executionStart - captureStart,
      forced_layout_ms: script.forcedStyleAndLayoutDuration, pause_ms: script.pauseDuration,
      invoker: script.invoker, invoker_type: script.invokerType,
      source_url: diagnosticSourceUrl(script.sourceURL), function_name: script.sourceFunctionName,
      char_position: script.sourceCharPosition, window_attribution: script.windowAttribution,
    })),
  })
}
