import type { Ref } from 'vue'
import { subscribeAppEvents } from '../../composables/useAppEventStream'


const GRAPH_STRUCTURE_REFRESH_DELAY_MS = 250
const graphStructureEvents = new Set(['graph_save_api'])


export function createBoardRuntimeRefresh(options: {
  currentGraphId: Ref<string | null>
  applyNodeRuntimeEvent: (payload: Record<string, unknown>) => void
  refreshNodeConfigs: () => Promise<void>
  refreshGraphLinks: () => Promise<void>
}) {
  let graphEventStreamKey = ''
  let stopGraphEvents: (() => void) | null = null
  let graphStructureRefreshTimer: number | null = null
  let graphStructureRefreshInFlight = false
  let streamResyncInFlight = false

  function resyncAfterStreamGap() {
    if (streamResyncInFlight) return
    streamResyncInFlight = true
    Promise.all([options.refreshNodeConfigs(), options.refreshGraphLinks()])
      .catch((error) => console.error('Failed to resync board after an event stream gap.', error))
      .finally(() => {
        streamResyncInFlight = false
      })
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
        console.error('Failed to refresh graph links from workspace events.', error)
      } finally {
        graphStructureRefreshInFlight = false
      }
    }, GRAPH_STRUCTURE_REFRESH_DELAY_MS)
  }

  function stopGraphEventStream() {
    stopGraphEvents?.()
    stopGraphEvents = null
    graphEventStreamKey = ''
    if (graphStructureRefreshTimer != null) {
      window.clearTimeout(graphStructureRefreshTimer)
      graphStructureRefreshTimer = null
    }
    graphStructureRefreshInFlight = false
    streamResyncInFlight = false
  }

  function startGraphEventStream() {
    const graphId = options.currentGraphId.value || 'default'
    if (stopGraphEvents && graphEventStreamKey === graphId) return
    stopGraphEventStream()
    graphEventStreamKey = graphId
    stopGraphEvents = subscribeAppEvents((payload) => {
      if (String(payload.event || '').trim() === 'stream_gap') {
        resyncAfterStreamGap()
        return
      }
      if ((options.currentGraphId.value || 'default') !== graphId) return
      if (String(payload.graph_id || '').trim() !== graphId) return
      const eventName = String(payload.event || '').trim()
      if (!eventName || eventName === 'node_live') return
      if (payload.node_runtime && typeof payload.node_runtime === 'object') {
        options.applyNodeRuntimeEvent(payload)
      }
      if (graphStructureEvents.has(eventName)) scheduleGraphStructureRefresh()
    })
  }

  return {
    startGraphEventStream,
    stopGraphEventStream,
  }
}
