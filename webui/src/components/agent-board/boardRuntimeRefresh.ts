import type { Ref } from 'vue'
import { graphEventsStreamUrl } from '../../api'

const ACTIVE_REFRESH_MS = 500
const ACTIVE_REFRESH_IDLE_LIMIT = 3
const GRAPH_EVENT_REFRESH_DELAY_MS = 50

const nodeRuntimeGraphEvents = new Set([
  'emit_enqueued',
  'node_dequeue',
  'node_output',
  'node_error',
  'node_state_set',
  'node_message_done',
  'runtime_notice',
  'server_tool_activity',
  'tool_call_start',
  'tool_call_end',
  'node_control',
  'node_working_recovered',
  'event_dispatch_enqueue',
  'propagate_enqueue',
  'startup_node_state_recovered',
])

const graphStructureEvents = new Set([
  'graph_save_api',
])

export function createBoardRuntimeRefresh(options: {
  currentGraphId: Ref<string | null>
  refreshNodeConfigs: () => Promise<void>
  refreshGraphLinks: () => Promise<void>
  hasActiveNodeWork: () => boolean
  requestMemoryRefresh?: () => void
}) {
  let activeNodeRefreshTimer: number | null = null
  let activeRefreshSessionId = 0
  let activeRefreshIdleCount = 0
  let graphEventSource: EventSource | null = null
  let graphEventStreamKey = ''
  let graphEventRefreshTimer: number | null = null
  let graphEventRefreshInFlight = false
  let graphStructureRefreshTimer: number | null = null
  let graphStructureRefreshInFlight = false

  function stopActiveNodeRefresh() {
    if (activeNodeRefreshTimer != null) {
      window.clearTimeout(activeNodeRefreshTimer)
      activeNodeRefreshTimer = null
    }
    activeRefreshSessionId += 1
    activeRefreshIdleCount = 0
  }

  function isNodeRuntimeGraphEvent(eventName: string) {
    return nodeRuntimeGraphEvents.has(eventName)
  }

  function isGraphStructureEvent(eventName: string) {
    return graphStructureEvents.has(eventName)
  }

  function scheduleGraphEventRefresh() {
    if (graphEventRefreshTimer != null) return
    graphEventRefreshTimer = window.setTimeout(async () => {
      graphEventRefreshTimer = null
      if (graphEventRefreshInFlight) {
        scheduleGraphEventRefresh()
        return
      }
      graphEventRefreshInFlight = true
      try {
        await options.refreshNodeConfigs()
      } catch (error) {
        console.error('Failed to refresh node configs from graph event stream.', error)
      }
      try {
        options.requestMemoryRefresh?.()
      } finally {
        graphEventRefreshInFlight = false
      }
    }, GRAPH_EVENT_REFRESH_DELAY_MS)
  }

  function scheduleGraphStructureRefresh() {
    if (graphStructureRefreshTimer != null) return
    graphStructureRefreshTimer = window.setTimeout(async () => {
      graphStructureRefreshTimer = null
      if (graphStructureRefreshInFlight) {
        scheduleGraphStructureRefresh()
        return
      }
      graphStructureRefreshInFlight = true
      try {
        await options.refreshGraphLinks()
      } catch (error) {
        console.error('Failed to refresh graph links from graph event stream.', error)
      } finally {
        graphStructureRefreshInFlight = false
      }
    }, GRAPH_EVENT_REFRESH_DELAY_MS)
  }

  function stopGraphEventStream() {
    if (graphEventSource) {
      graphEventSource.close()
      graphEventSource = null
    }
    graphEventStreamKey = ''
    if (graphEventRefreshTimer != null) {
      window.clearTimeout(graphEventRefreshTimer)
      graphEventRefreshTimer = null
    }
    if (graphStructureRefreshTimer != null) {
      window.clearTimeout(graphStructureRefreshTimer)
      graphStructureRefreshTimer = null
    }
    graphEventRefreshInFlight = false
    graphStructureRefreshInFlight = false
  }

  function startGraphEventStream() {
    const graphId = options.currentGraphId.value || 'default'
    if (graphEventSource && graphEventStreamKey === graphId) return
    stopGraphEventStream()
    const source = new EventSource(graphEventsStreamUrl(graphId))
    graphEventSource = source
    graphEventStreamKey = graphId
    source.onmessage = (event) => {
      if (graphEventSource !== source) return
      if ((options.currentGraphId.value || 'default') !== graphId) return
      try {
        const payload = JSON.parse(String(event.data || '{}'))
        const eventName = String(payload?.event || '').trim()
        if (isNodeRuntimeGraphEvent(eventName)) {
          scheduleGraphEventRefresh()
        }
        if (isGraphStructureEvent(eventName)) {
          scheduleGraphStructureRefresh()
        }
      } catch (error) {
        console.error('Failed to process graph event stream payload.', error)
      }
    }
    source.onerror = (event) => {
      if (graphEventSource !== source) return
      console.error('Graph event stream connection failed.', event)
      if ((options.currentGraphId.value || 'default') !== graphId) {
        stopGraphEventStream()
      }
    }
  }

  function scheduleActiveNodeRefresh() {
    if (activeNodeRefreshTimer != null) return
    const sessionId = ++activeRefreshSessionId
    activeRefreshIdleCount = 0

    const runTick = async () => {
      if (sessionId !== activeRefreshSessionId) return
      try {
        await options.refreshNodeConfigs()
      } catch {
        // Runtime refresh is best-effort; explicit user actions still report errors.
      }
      if (sessionId !== activeRefreshSessionId) return
      activeRefreshIdleCount = options.hasActiveNodeWork() ? 0 : activeRefreshIdleCount + 1
      if (activeRefreshIdleCount >= ACTIVE_REFRESH_IDLE_LIMIT) {
        activeNodeRefreshTimer = null
        return
      }
      activeNodeRefreshTimer = window.setTimeout(runTick, ACTIVE_REFRESH_MS)
    }

    activeNodeRefreshTimer = window.setTimeout(runTick, ACTIVE_REFRESH_MS)
  }

  return {
    scheduleActiveNodeRefresh,
    startGraphEventStream,
    stopActiveNodeRefresh,
    stopGraphEventStream,
  }
}
