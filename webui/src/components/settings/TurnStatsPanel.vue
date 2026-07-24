<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TurnTokenProviderStats, TurnTokenStat } from '../../settingsApi'

const props = defineProps<{
  providerId: string
  providerStats: TurnTokenProviderStats | null
}>()

const selectedTraceId = ref('')
const selectedTokenKind = ref<'input' | 'output'>('input')
const pixelsPerMinute = ref(80)
const hoveredCumulativeIndex = ref<number | null>(null)
const hoveredRequestIndex = ref<number | null>(null)

watch(
  () => [props.providerId, props.providerStats?.latest_turn?.trace_id] as const,
  () => {
    selectedTraceId.value = props.providerStats?.latest_turn?.trace_id || ''
  },
  { immediate: true },
)

const selectedTurn = computed<TurnTokenStat | null>(() => {
  const turns = props.providerStats?.recent_turns || []
  return turns.find((turn) => turn.trace_id === selectedTraceId.value)
    || props.providerStats?.latest_turn
    || null
})
const hasServerUsage = computed(() => (selectedTurn.value?.usage_request_count || 0) > 0)

const minimumChartWidth = 520
const minimumPixelsPerMinute = 40
const maximumPixelsPerMinute = 320
const pixelsPerMinuteStep = 20
const cumulativeHeight = 300
const requestHeight = 260
const padding = { left: 62, right: 24, top: 28, bottom: 54 }
const timeline = computed(() => {
  const points = selectedTurn.value?.chart_points || []
  const parsed = points.map((point) => parseTimestamp(point.at))
  const valid = parsed.every((value) => value != null)
  const firstTimestamp = parsed[0]
  const lastTimestamp = parsed[parsed.length - 1]
  const start = valid && firstTimestamp != null ? firstTimestamp : 0
  const end = valid && lastTimestamp != null ? lastTimestamp : start
  return {
    start,
    duration: Math.max(1, end - start),
    elapsed: parsed.map((value, index) => {
      if (valid && value != null) return Math.max(0, value - start)
      return points.length <= 1 ? 0 : index / (points.length - 1)
    }),
    usesTimestamps: valid,
  }
})
const width = computed(() => {
  const durationMinutes = timeline.value.duration / 60_000
  return Math.max(
    minimumChartWidth,
    padding.left + padding.right + durationMinutes * pixelsPerMinute.value,
  )
})
const timelinePlotWidth = computed(() => width.value - padding.left - padding.right)
const cumulativePlotHeight = cumulativeHeight - padding.top - padding.bottom
const requestPlotHeight = requestHeight - padding.top - padding.bottom

const cumulativeMaxTokens = computed(() => {
  const points = selectedTurn.value?.chart_points || []
  const key = selectedTokenKind.value === 'input'
    ? 'cumulative_input_tokens'
    : 'cumulative_output_tokens'
  const maximum = Math.max(0, ...points.map((point) => point[key]))
  return maximum > 0 ? maximum : 1
})

const positionedPoints = computed(() => {
  const points = selectedTurn.value?.chart_points || []
  return points.map((point, index) => ({
    ...point,
    elapsed_ms: timeline.value.usesTimestamps
      ? timeline.value.elapsed[index] || 0
      : ((timeline.value.elapsed[index] || 0) * timeline.value.duration),
    x: padding.left + (
      timeline.value.usesTimestamps
        ? (timeline.value.elapsed[index] || 0) / timeline.value.duration
        : (timeline.value.elapsed[index] || 0)
    ) * timelinePlotWidth.value,
  }))
})

const timelineTicks = computed(() => {
  const duration = timeline.value.duration
  const interval = timelineInterval(duration)
  const elapsedValues: number[] = []
  for (let elapsed = 0; elapsed <= duration; elapsed += interval) elapsedValues.push(elapsed)
  if (elapsedValues[elapsedValues.length - 1] !== duration) elapsedValues.push(duration)
  return elapsedValues.map((elapsed) => ({
    elapsed,
    label: formatElapsed(elapsed),
    x: padding.left + (elapsed / duration) * timelinePlotWidth.value,
  }))
})

const cumulativeChartPoints = computed(() => {
  return positionedPoints.value.map((point) => ({
    ...point,
    value: selectedTokenKind.value === 'input'
      ? point.cumulative_input_tokens
      : point.cumulative_output_tokens,
    y: tokenY(
      selectedTokenKind.value === 'input'
        ? point.cumulative_input_tokens
        : point.cumulative_output_tokens,
      cumulativeMaxTokens.value,
      cumulativePlotHeight,
    ),
  }))
})

const requestMaxTokens = computed(() => {
  const key = selectedTokenKind.value === 'input'
    ? 'request_input_tokens'
    : 'request_output_tokens'
  const values = positionedPoints.value
    .map((point) => point[key])
    .filter((value): value is number => value != null)
  const maximum = Math.max(0, ...values)
  return maximum > 0 ? maximum : 1
})

const requestChartPoints = computed(() => {
  const key = selectedTokenKind.value === 'input'
    ? 'request_input_tokens'
    : 'request_output_tokens'
  return positionedPoints.value
    .filter((point) => point[key] != null)
    .map((point) => {
      const value = point[key] as number
      return {
        ...point,
        value,
        y: tokenY(value, requestMaxTokens.value, requestPlotHeight),
      }
    })
})

const cumulativeYTicks = computed(() => buildYTicks(cumulativeMaxTokens.value, cumulativePlotHeight))
const requestYTicks = computed(() => buildYTicks(requestMaxTokens.value, requestPlotHeight))

const cumulativeResponsePoints = computed(() => cumulativeChartPoints.value.filter((point) => point.kind === 'response'))
const terminalPoint = computed(() => positionedPoints.value.find((point) => point.kind === 'terminal') || null)
const cumulativePolyline = computed(() => polyline(
  cumulativeChartPoints.value.filter((point) => point.kind !== 'terminal'),
  'y',
))
const requestPolyline = computed(() => polyline(requestChartPoints.value, 'y'))
const hoveredCumulativePoint = computed(() => {
  if (hoveredCumulativeIndex.value == null) return null
  return cumulativeResponsePoints.value[hoveredCumulativeIndex.value] || null
})
const hoveredRequestPoint = computed(() => {
  if (hoveredRequestIndex.value == null) return null
  return requestChartPoints.value[hoveredRequestIndex.value] || null
})

function tokenY(value: number, maximum: number, plotHeight: number) {
  return padding.top + plotHeight - (Math.max(0, value) / maximum) * plotHeight
}

function buildYTicks(maximum: number, plotHeight: number) {
  return Array.from({ length: 5 }, (_, index) => ({
    value: Math.round((maximum * (4 - index)) / 4),
    y: padding.top + (plotHeight * index) / 4,
  }))
}

function polyline<T extends { x: number }>(points: T[], key: keyof T) {
  return points.map((point) => `${point.x},${String(point[key])}`).join(' ')
}

function changeTimeScale(delta: number) {
  pixelsPerMinute.value = Math.min(
    maximumPixelsPerMinute,
    Math.max(minimumPixelsPerMinute, pixelsPerMinute.value + delta),
  )
}

function parseTimestamp(value: string) {
  const normalized = String(value || '')
    .trim()
    .replace(' ', 'T')
    .replace(/(\.\d{3})\d+$/, '$1')
  const timestamp = Date.parse(normalized)
  return Number.isFinite(timestamp) ? timestamp : null
}

function timelineInterval(durationMs: number) {
  const intervals = [1_000, 5_000, 10_000, 30_000, 60_000, 5 * 60_000, 15 * 60_000, 60 * 60_000]
  return intervals.find((interval) => durationMs / interval <= 8) || 6 * 60 * 60_000
}

function formatElapsed(valueMs: number) {
  const totalSeconds = Math.max(0, Math.round(valueMs / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours) return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

function updateHoveredPoint(event: MouseEvent, chart: 'cumulative' | 'request') {
  const svg = event.currentTarget as SVGSVGElement
  const bounds = svg.getBoundingClientRect()
  if (bounds.width <= 0) return

  const svgX = ((event.clientX - bounds.left) / bounds.width) * width.value
  const points = chart === 'cumulative' ? cumulativeResponsePoints.value : requestChartPoints.value
  const firstPoint = points[0]
  if (!firstPoint) return

  let nearestIndex = 0
  let nearestDistance = Math.abs(firstPoint.x - svgX)
  for (let index = 1; index < points.length; index += 1) {
    const point = points[index]
    if (!point) continue
    const distance = Math.abs(point.x - svgX)
    if (distance < nearestDistance) {
      nearestIndex = index
      nearestDistance = distance
    }
  }

  if (chart === 'cumulative') hoveredCumulativeIndex.value = nearestIndex
  else hoveredRequestIndex.value = nearestIndex
}

function tooltipX(x: number) {
  const tooltipWidth = 214
  return Math.min(Math.max(x + 12, padding.left), width.value - padding.right - tooltipWidth)
}

function tooltipY(y: number, chartHeight: number) {
  const tooltipHeight = 54
  const preferred = y - tooltipHeight - 12
  return preferred >= padding.top
    ? preferred
    : Math.min(y + 12, chartHeight - padding.bottom - tooltipHeight)
}

function formatTokens(value: number | undefined) {
  return new Intl.NumberFormat().format(value || 0)
}

function formatOptionalTokens(value: number | undefined) {
  return value == null ? '—' : formatTokens(value)
}

function markerLabelY(y: number) {
  return y < padding.top + 18 ? y + 20 : y - 10
}

function elapsedFromStart(value: string) {
  const timestamp = parseTimestamp(value)
  if (timestamp == null || !timeline.value.usesTimestamps) return '—'
  return formatElapsed(Math.max(0, timestamp - timeline.value.start))
}

function shortTrace(value: string) {
  return value.length > 12 ? `${value.slice(0, 12)}…` : value
}
</script>

<template>
  <section class="turn-stats-panel">
    <div class="turn-stats-head">
      <div>
        <div class="turn-stats-title">Model Turn Statistics</div>
        <p>{{ providerId || 'No provider selected' }} · every dot is one completed model response</p>
      </div>
      <select
        v-if="providerStats?.recent_turns.length"
        v-model="selectedTraceId"
        class="turn-selector"
        aria-label="Select turn"
      >
        <option v-for="turn in providerStats.recent_turns" :key="turn.trace_id" :value="turn.trace_id">
          {{ turn.completed_at }} · {{ turn.status }} · {{ shortTrace(turn.trace_id) }}
        </option>
      </select>
    </div>

    <template v-if="selectedTurn">
      <div class="turn-token-metrics">
        <div>
          <span>First model turn input</span>
          <strong>{{ selectedTurn.first_response ? formatOptionalTokens(selectedTurn.first_response.usage.input_tokens) : '—' }}</strong>
        </div>
        <div>
          <span>First model turn output</span>
          <strong>{{ selectedTurn.first_response ? formatOptionalTokens(selectedTurn.first_response.usage.output_tokens) : '—' }}</strong>
        </div>
        <div>
          <span>Accumulated API usage</span>
          <strong>{{ hasServerUsage ? formatTokens(selectedTurn.accumulated_usage.total_tokens) : '—' }}</strong>
        </div>
        <div>
          <span>Model turns with usage</span>
          <strong>{{ selectedTurn.usage_request_count }} / {{ selectedTurn.model_turn_count }}</strong>
        </div>
      </div>

      <div v-if="selectedTurn.usage_status === 'missing' || selectedTurn.usage_status === 'partial'" class="turn-usage-warning">
        Server usage is {{ selectedTurn.usage_status }}: {{ selectedTurn.missing_usage_request_count }} of
        {{ selectedTurn.model_turn_count }} completed model turns did not return token usage. Missing usage is not counted as zero.
      </div>

      <div class="model-turn-explanation">
        <strong>{{ selectedTurn.model_turn_count }} model turns</strong>
        <span>One numbered dot per complete provider response. The green dashed line marks node-run completion.</span>
        <span v-if="selectedTurn.incomplete_request_count">{{ selectedTurn.incomplete_request_count }} request attempts did not complete.</span>
      </div>

      <template v-if="hasServerUsage">
      <div class="turn-token-kind-switch" role="group" aria-label="Token type">
        <button
          type="button"
          :class="{ active: selectedTokenKind === 'input' }"
          :aria-pressed="selectedTokenKind === 'input'"
          @click="selectedTokenKind = 'input'"
        >
          Input
        </button>
        <button
          type="button"
          :class="{ active: selectedTokenKind === 'output' }"
          :aria-pressed="selectedTokenKind === 'output'"
          @click="selectedTokenKind = 'output'"
        >
          Output
        </button>
      </div>

      <div class="turn-chart-zoom" aria-label="Timeline scale controls">
        <span>Time scale</span>
        <button
          type="button"
          aria-label="Zoom out"
          :disabled="pixelsPerMinute <= minimumPixelsPerMinute"
          @click="changeTimeScale(-pixelsPerMinuteStep)"
        >−</button>
        <input
          v-model.number="pixelsPerMinute"
          type="range"
          :min="minimumPixelsPerMinute"
          :max="maximumPixelsPerMinute"
          :step="pixelsPerMinuteStep"
          aria-label="Timeline pixels per minute"
        >
        <button
          type="button"
          aria-label="Zoom in"
          :disabled="pixelsPerMinute >= maximumPixelsPerMinute"
          @click="changeTimeScale(pixelsPerMinuteStep)"
        >+</button>
        <output>{{ pixelsPerMinute }}px/min</output>
        <button
          v-if="pixelsPerMinute !== 80"
          type="button"
          class="turn-chart-zoom-reset"
          @click="pixelsPerMinute = 80"
        >Reset</button>
      </div>

      <div class="turn-chart-scroll">
        <div class="turn-chart-stack" :style="{ width: `${width}px` }">
          <section class="turn-chart-section">
            <div class="turn-chart-section-head">
              <strong>Cumulative {{ selectedTokenKind }} token usage</strong>
              <div class="turn-chart-legend" aria-hidden="true">
                <span :class="selectedTokenKind">Cumulative {{ selectedTokenKind }}</span>
              </div>
            </div>
            <svg
              class="turn-chart"
              :viewBox="`0 0 ${width} ${cumulativeHeight}`"
              role="img"
              :aria-label="`Cumulative ${selectedTokenKind} token growth chart`"
              @mousemove="updateHoveredPoint($event, 'cumulative')"
              @mouseleave="hoveredCumulativeIndex = null"
            >
              <g class="turn-chart-grid">
                <template v-for="tick in cumulativeYTicks" :key="tick.y">
                  <line :x1="padding.left" :x2="width - padding.right" :y1="tick.y" :y2="tick.y" />
                  <text :x="padding.left - 10" :y="tick.y + 4" text-anchor="end">{{ formatTokens(tick.value) }}</text>
                </template>
                <template v-for="tick in timelineTicks" :key="`cumulative-time:${tick.elapsed}`">
                  <line class="timeline-grid-line" :x1="tick.x" :x2="tick.x" :y1="padding.top" :y2="cumulativeHeight - padding.bottom" />
                  <text class="timeline-label" :x="tick.x" :y="cumulativeHeight - 25" text-anchor="middle">{{ tick.label }}</text>
                </template>
              </g>

              <polyline class="token-line" :class="selectedTokenKind" :points="cumulativePolyline" />

              <line v-if="terminalPoint" class="persisted-line" :x1="terminalPoint.x" :x2="terminalPoint.x" :y1="padding.top" :y2="cumulativeHeight - padding.bottom" />
              <g v-for="point in cumulativeResponsePoints" :key="`cumulative-response:${point.request_index}`" class="turn-chart-point model-turn-point">
                <circle :class="selectedTokenKind" :cx="point.x" :cy="point.y" r="4" />
                <text :x="point.x" :y="markerLabelY(point.y)" text-anchor="middle">R{{ point.request_index }}</text>
              </g>

              <g v-if="hoveredCumulativePoint" class="turn-chart-tooltip" aria-live="polite">
                <line class="hover-guide" :x1="hoveredCumulativePoint.x" :x2="hoveredCumulativePoint.x" :y1="padding.top" :y2="cumulativeHeight - padding.bottom" />
                <circle :class="selectedTokenKind" :cx="hoveredCumulativePoint.x" :cy="hoveredCumulativePoint.y" r="5" />
                <g :transform="`translate(${tooltipX(hoveredCumulativePoint.x)}, ${tooltipY(hoveredCumulativePoint.y, cumulativeHeight)})`">
                  <rect width="214" height="54" rx="6" />
                  <text x="10" y="18">{{ hoveredCumulativePoint.label }} · +{{ formatElapsed(hoveredCumulativePoint.elapsed_ms) }}</text>
                  <text class="tooltip-value" x="10" y="38">Cumulative {{ selectedTokenKind }}: {{ formatTokens(hoveredCumulativePoint.value) }}</text>
                </g>
              </g>
            </svg>
          </section>

          <section class="turn-chart-section request-chart-section">
            <div class="turn-chart-section-head">
              <strong>Current request {{ selectedTokenKind }} token usage</strong>
              <div class="turn-chart-legend request" aria-hidden="true">
                <span :class="selectedTokenKind">Request {{ selectedTokenKind }}</span>
              </div>
            </div>
            <svg
              class="turn-chart"
              :viewBox="`0 0 ${width} ${requestHeight}`"
              role="img"
              :aria-label="`Current request ${selectedTokenKind} token usage chart`"
              @mousemove="updateHoveredPoint($event, 'request')"
              @mouseleave="hoveredRequestIndex = null"
            >
              <g class="turn-chart-grid">
                <template v-for="tick in requestYTicks" :key="tick.y">
                  <line :x1="padding.left" :x2="width - padding.right" :y1="tick.y" :y2="tick.y" />
                  <text :x="padding.left - 10" :y="tick.y + 4" text-anchor="end">{{ formatTokens(tick.value) }}</text>
                </template>
                <template v-for="tick in timelineTicks" :key="`request-time:${tick.elapsed}`">
                  <line class="timeline-grid-line" :x1="tick.x" :x2="tick.x" :y1="padding.top" :y2="requestHeight - padding.bottom" />
                  <text class="timeline-label" :x="tick.x" :y="requestHeight - 25" text-anchor="middle">{{ tick.label }}</text>
                </template>
              </g>

              <polyline class="token-line request" :class="selectedTokenKind" :points="requestPolyline" />

              <line v-if="terminalPoint" class="persisted-line" :x1="terminalPoint.x" :x2="terminalPoint.x" :y1="padding.top" :y2="requestHeight - padding.bottom" />
              <g v-for="point in requestChartPoints" :key="`request-response:${point.request_index}`" class="turn-chart-point model-turn-point">
                <circle :class="selectedTokenKind" :cx="point.x" :cy="point.y" r="4" />
                <text :x="point.x" :y="markerLabelY(point.y)" text-anchor="middle">R{{ point.request_index }}</text>
              </g>


              <g v-if="hoveredRequestPoint" class="turn-chart-tooltip" aria-live="polite">
                <line class="hover-guide" :x1="hoveredRequestPoint.x" :x2="hoveredRequestPoint.x" :y1="padding.top" :y2="requestHeight - padding.bottom" />
                <circle :class="selectedTokenKind" :cx="hoveredRequestPoint.x" :cy="hoveredRequestPoint.y" r="5" />
                <g :transform="`translate(${tooltipX(hoveredRequestPoint.x)}, ${tooltipY(hoveredRequestPoint.y, requestHeight)})`">
                  <rect width="214" height="54" rx="6" />
                  <text x="10" y="18">{{ hoveredRequestPoint.label }} · +{{ formatElapsed(hoveredRequestPoint.elapsed_ms) }}</text>
                  <text class="tooltip-value" x="10" y="38">Request {{ selectedTokenKind }}: {{ formatTokens(hoveredRequestPoint.value) }}</text>
                </g>
              </g>
            </svg>
          </section>
        </div>
      </div>
      </template>

      <div v-if="selectedTurn.requests.length" class="model-turn-records">
        <div v-for="request in selectedTurn.requests" :key="request.request_index" class="model-turn-record">
          <strong>R{{ request.request_index }}</strong>
          <span>+{{ elapsedFromStart(request.received_at) }}</span>
          <span>in {{ formatOptionalTokens(request.usage.input_tokens) }}</span>
          <span>out {{ formatOptionalTokens(request.usage.output_tokens) }}</span>
        </div>
      </div>

      <div class="turn-stats-foot">
        <span>{{ selectedTurn.graph_id }} / {{ selectedTurn.node_id }}</span>
        <span>{{ selectedTurn.model_turn_count }} model turns</span>
        <span>Started {{ selectedTurn.started_at || '-' }}</span>
        <span>Duration {{ formatElapsed(timeline.duration) }}</span>
        <span>{{ selectedTurn.status }} {{ selectedTurn.completed_at }}</span>
        <span v-if="selectedTurn.error" class="turn-error">{{ selectedTurn.error }}</span>
      </div>
    </template>

    <div v-else class="turn-stats-empty">
      No terminal turn for {{ providerId || 'this provider' }} in the selected scope.
    </div>
  </section>
</template>

<style scoped src="./TurnStatsPanel.css"></style>
