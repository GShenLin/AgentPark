<script setup lang="ts">
import { ref } from 'vue'
import {
  getToolFailureHistory,
  type ToolFailureAnalysis,
  type ToolFailureHistory,
} from '../../settingsApi'
import {
  callKey,
  failureReason,
  formatStructuredValue,
  invocationLabel,
  invocationText,
  shortText,
  statusLabel,
} from './toolStatsFormatting'

const props = defineProps<{
  analysis: ToolFailureAnalysis
  graphId?: string
  scopeHours?: number
}>()

const selectedToolName = ref('')
const history = ref<ToolFailureHistory | null>(null)
const loading = ref(false)
const error = ref('')
let requestId = 0

async function toggleTool(toolName: string) {
  if (selectedToolName.value === toolName) {
    closeHistory()
    return
  }

  const currentRequestId = ++requestId
  selectedToolName.value = toolName
  history.value = null
  error.value = ''
  loading.value = true
  try {
    const next = await getToolFailureHistory(toolName, props.graphId || '', props.scopeHours || 0)
    if (currentRequestId === requestId) history.value = next
  } catch (e: any) {
    if (currentRequestId === requestId) error.value = String(e?.message || e)
  } finally {
    if (currentRequestId === requestId) loading.value = false
  }
}

function closeHistory() {
  selectedToolName.value = ''
  history.value = null
  error.value = ''
  loading.value = false
  requestId += 1
}
</script>

<template>
  <section class="failure-patterns">
    <div class="tool-section-title">
      Failure Patterns
      <span>{{ analysis.total_failures }} failures across {{ analysis.affected_tool_count }} tools / {{ analysis.analyzed_call_count }} calls analyzed</span>
    </div>
    <div v-if="analysis.shared_patterns.length" class="failure-pattern-list">
      <article v-for="pattern in analysis.shared_patterns" :key="pattern.category">
        <strong>{{ pattern.category }}</strong>
        <span>{{ pattern.count }} failures / {{ pattern.tool_count }} tools</span>
        <small>{{ pattern.tools.join(', ') }}</small>
      </article>
    </div>
    <div v-else class="tool-stats-empty">No cross-tool common pattern in the recent records.</div>

    <details class="per-tool-analysis">
      <summary>Per-tool failure breakdown</summary>
      <div class="per-tool-grid">
        <button
          v-for="tool in Object.values(analysis.tools)"
          :key="tool.tool_name"
          type="button"
          class="per-tool-card"
          :class="{ selected: selectedToolName === tool.tool_name }"
          :aria-expanded="selectedToolName === tool.tool_name"
          @click="toggleTool(tool.tool_name)"
        >
          <span class="per-tool-card-head">
            <strong>{{ tool.tool_name }}</strong>
            <span class="per-tool-card-toggle">{{ selectedToolName === tool.tool_name ? 'Collapse' : 'View every failure' }}</span>
          </span>
          <span class="per-tool-card-count">{{ tool.failure_count }} failures</span>
          <small>{{ Object.entries(tool.categories).map(([name, count]) => `${name}: ${count}`).join(' / ') }}</small>
          <small v-if="Object.keys(tool.reasons).length">Top reason: {{ Object.entries(tool.reasons)[0]?.[0] }}</small>
        </button>
      </div>

      <section v-if="selectedToolName" class="failure-history">
        <div class="failure-history-head">
          <div>
            <strong>{{ selectedToolName }}</strong>
            <span v-if="history">{{ history.failure_count }} failures in {{ history.analyzed_call_count }} analyzed calls</span>
          </div>
          <button type="button" @click="closeHistory">Close</button>
        </div>

        <div v-if="loading" class="tool-stats-empty">Loading failure details...</div>
        <div v-else-if="error" class="tool-stats-error">{{ error }}</div>
        <div v-else-if="history?.calls.length" class="failure-history-list">
          <details
            v-for="(call, index) in history.calls"
            :key="callKey(call)"
            class="failure-history-call"
            :open="index === 0"
          >
            <summary>
              <span>
                <strong>#{{ index + 1 }} · {{ statusLabel(call) }}</strong>
                <small>{{ shortText(call.error, shortText(call.result_preview, 'No error summary')) }}</small>
              </span>
              <span class="failure-history-call-meta">
                <small>{{ call.duration_ms ?? '-' }} ms</small>
                <small>{{ call.recorded_at }}</small>
              </span>
            </summary>

            <div class="failure-history-body">
              <dl class="call-review-meta">
                <div><dt>Provider</dt><dd>{{ call.provider_id }}</dd></div>
                <div><dt>Graph / Node</dt><dd>{{ shortText(call.graph_id) }} / {{ shortText(call.node_id) }}</dd></div>
                <div><dt>Call ID</dt><dd>{{ shortText(call.call_id) }}</dd></div>
                <div><dt>Started / Completed</dt><dd>{{ shortText(call.started_at) }} / {{ shortText(call.completed_at) }}</dd></div>
              </dl>

              <div class="call-review-grid">
                <article>
                  <h4>{{ invocationLabel(call) }}</h4>
                  <pre>{{ invocationText(call) }}</pre>
                </article>
                <article class="failure">
                  <h4>Failure reason</h4>
                  <pre>{{ failureReason(call) }}</pre>
                </article>
              </div>

              <article class="call-result">
                <h4>Complete tool result</h4>
                <pre>{{ formatStructuredValue(call.result, shortText(call.result_preview)) }}</pre>
              </article>

              <article v-if="call.diagnostics?.length" class="call-result diagnostics">
                <h4>Diagnostics</h4>
                <pre>{{ call.diagnostics.join('\n') }}</pre>
              </article>
            </div>
          </details>
        </div>
        <div v-else class="tool-stats-empty">No failure records found for this tool.</div>
      </section>
    </details>
  </section>
</template>

<style scoped src="./ToolFailurePatternsPanel.css"></style>
