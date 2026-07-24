<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  clearToolStats,
  deleteOptionalMemory,
  getToolStats,
  type ToolCallStatRecord,
  type ToolStatsDocument,
  type ToolStatsProviderSummary,
} from '../../settingsApi'
import ToolFailurePatternsPanel from './ToolFailurePatternsPanel.vue'
import TurnStatsPanel from './TurnStatsPanel.vue'
import {
  callKey,
  failureReason,
  formatStructuredValue,
  invocationLabel,
  invocationText,
  shortText,
  statusLabel,
} from './toolStatsFormatting'

const stats = ref<ToolStatsDocument | null>(null)
const selectedProviderId = ref('')
const selectedCallKey = ref('')
const scopeGraphId = ref('')
const scopeHours = ref(0)
const loading = ref(false)
const clearing = ref(false)
const deletingOptionalMemory = ref(false)
const error = ref('')
const operationStatus = ref('')

const providerOptions = computed(() => {
  const ids = new Set([
    ...Object.keys(stats.value?.summary?.providers || {}),
    ...Object.keys(stats.value?.turn_stats?.providers || {}),
  ])
  return Array.from(ids).map((providerId) => {
    const toolStats = stats.value?.summary?.providers?.[providerId]
    const turnStats = stats.value?.turn_stats?.providers?.[providerId]
    return {
      provider_id: providerId,
      success: toolStats?.success || 0,
      total: toolStats?.total || 0,
      turn_count: turnStats?.turn_count || 0,
      usage_turn_count: turnStats?.usage_turn_count || 0,
      missing_usage_turn_count: turnStats?.missing_usage_turn_count || 0,
      model_turn_count: turnStats?.model_turn_count || 0,
      usage_model_turn_count: turnStats?.usage_model_turn_count || 0,
    }
  }).sort((a, b) => b.total - a.total || b.turn_count - a.turn_count || a.provider_id.localeCompare(b.provider_id))
})

const selectedProvider = computed<ToolStatsProviderSummary | null>(() => {
  return stats.value?.summary?.providers?.[selectedProviderId.value] || null
})

const providerTools = computed(() => {
  const tools = selectedProvider.value?.tools || {}
  return Object.values(tools).sort((a, b) => b.total - a.total || a.tool_name.localeCompare(b.tool_name))
})

const recentCalls = computed<ToolCallStatRecord[]>(() => stats.value?.recent_calls || [])
const providerRecentCalls = computed<ToolCallStatRecord[]>(() => {
  if (!selectedProviderId.value) return recentCalls.value
  return stats.value?.recent_calls_by_provider?.[selectedProviderId.value] || []
})
const providerFailureCalls = computed(() => providerRecentCalls.value.filter((call) => !call.success))
const failureAnalysis = computed(() => {
  if (!selectedProviderId.value) return stats.value?.failure_analysis || null
  return stats.value?.failure_analysis_by_provider?.[selectedProviderId.value] || null
})
const selectedCall = computed<ToolCallStatRecord | null>(() => {
  return providerRecentCalls.value.find((call) => callKey(call) === selectedCallKey.value)
    || providerFailureCalls.value[0]
    || providerRecentCalls.value[0]
    || null
})
const totalCalls = computed(() => selectedProvider.value?.total || 0)
const successCalls = computed(() => selectedProvider.value?.success || 0)
const failureCalls = computed(() => selectedProvider.value?.failure || 0)
const successRate = computed(() => {
  if (!totalCalls.value) return '0%'
  return `${Math.round((successCalls.value / totalCalls.value) * 100)}%`
})

function selectProvider(providerId: string) {
  selectedProviderId.value = providerId
  selectDefaultCall(providerId)
}

function selectCall(call: ToolCallStatRecord) {
  selectedCallKey.value = callKey(call)
}

function selectDefaultCall(providerId = selectedProviderId.value, calls = recentCalls.value) {
  const providerCalls = calls.filter((call) => call.provider_id === providerId)
  const next = providerCalls.find((call) => !call.success) || providerCalls[0]
  selectedCallKey.value = next ? callKey(next) : ''
}

async function loadStats() {
  loading.value = true
  error.value = ''
  operationStatus.value = ''
  try {
    const next = await getToolStats(scopeGraphId.value, scopeHours.value)
    stats.value = next
    const availableProviderIds = new Set([
      ...Object.keys(next.summary.providers || {}),
      ...Object.keys(next.turn_stats?.providers || {}),
    ])
    if (!selectedProviderId.value || !availableProviderIds.has(selectedProviderId.value)) {
      selectedProviderId.value = availableProviderIds.values().next().value || ''
    }
    selectDefaultCall(selectedProviderId.value, next.recent_calls || [])
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    loading.value = false
  }
}

function changeScope() {
  selectedCallKey.value = ''
  void loadStats()
}

async function clearStats() {
  const ok = window.confirm('Clear all tool stats?')
  if (!ok) return
  clearing.value = true
  error.value = ''
  operationStatus.value = ''
  try {
    const next = await clearToolStats(scopeGraphId.value, scopeHours.value)
    stats.value = next
    selectedCallKey.value = ''
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    clearing.value = false
  }
}

async function deleteOptionalMemoryFiles() {
  const ok = window.confirm('Delete every operational_memory.json file under the memories folder?')
  if (!ok) return
  deletingOptionalMemory.value = true
  error.value = ''
  operationStatus.value = ''
  try {
    const result = await deleteOptionalMemory()
    operationStatus.value = result.stdout || 'DeleteOptionalMemory completed.'
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    deletingOptionalMemory.value = false
  }
}

onMounted(loadStats)
</script>

<template>
  <div class="tool-stats">
    <aside class="tool-stats-side">
      <button type="button" class="tool-stats-action" :disabled="loading || clearing || deletingOptionalMemory" @click="loadStats">
        {{ loading ? 'Loading...' : 'Reload' }}
      </button>
      <button type="button" class="tool-stats-action danger" :disabled="loading || clearing || deletingOptionalMemory" @click="clearStats">
        {{ clearing ? 'Clearing...' : 'Clear' }}
      </button>
      <button
        type="button"
        class="tool-stats-action danger"
        :disabled="loading || clearing || deletingOptionalMemory"
        @click="deleteOptionalMemoryFiles"
      >
        {{ deletingOptionalMemory ? 'Deleting...' : 'DeleteOptionalMemory' }}
      </button>

      <button
        v-for="provider in providerOptions"
        :key="provider.provider_id"
        type="button"
        class="tool-provider-item"
        :class="{ active: selectedProviderId === provider.provider_id }"
        @click="selectProvider(provider.provider_id)"
      >
        <span>{{ provider.provider_id }}</span>
        <small>
          {{ provider.success }} / {{ provider.total }} tools · {{ provider.model_turn_count }} model turns · {{ provider.turn_count }} runs
          <template v-if="provider.missing_usage_turn_count"> · {{ provider.missing_usage_turn_count }} missing usage</template>
        </small>
      </button>

      <div v-if="!providerOptions.length && !loading" class="tool-stats-empty">No provider stats</div>
    </aside>

    <section class="tool-stats-main">
      <div class="tool-stats-head">
        <div>
          <h2>{{ selectedProviderId || 'Tool Statistics' }}</h2>
          <span>
            Scope: {{ scopeGraphId || 'all graphs' }} / {{ scopeHours ? `${scopeHours}h` : 'all time' }}
            <template v-if="stats?.summary.updated_at"> · updated {{ stats.summary.updated_at }}</template>
          </span>
        </div>
        <div class="tool-stats-scope-controls">
          <label>
            Graph
            <select v-model="scopeGraphId" @change="changeScope">
              <option value="">All graphs</option>
              <option v-for="graphId in stats?.scope.available_graph_ids || []" :key="graphId" :value="graphId">{{ graphId }}</option>
            </select>
          </label>
          <label>
            Window
            <select v-model.number="scopeHours" @change="changeScope">
              <option :value="0">All time</option>
              <option :value="24">24 hours</option>
              <option :value="168">7 days</option>
              <option :value="720">30 days</option>
            </select>
          </label>
        </div>
      </div>

      <div class="metric-grid">
        <div class="metric-item">
          <span>Provider Tool Calls</span>
          <strong>{{ totalCalls }}</strong>
        </div>
        <div class="metric-item">
          <span>Provider Success</span>
          <strong>{{ successCalls }}</strong>
        </div>
        <div class="metric-item">
          <span>Provider Failure</span>
          <strong>{{ failureCalls }}</strong>
        </div>
        <div class="metric-item">
          <span>Provider Rate</span>
          <strong>{{ successRate }}</strong>
        </div>
      </div>

      <div v-if="selectedProvider" class="provider-summary-line">
        <strong>{{ selectedProvider.success }} success</strong>
        <span>{{ selectedProvider.failure }} failure</span>
        <span>{{ selectedProvider.last_call_at }}</span>
      </div>

      <ToolFailurePatternsPanel
        v-if="failureAnalysis?.total_failures"
        :analysis="failureAnalysis"
        :graph-id="scopeGraphId"
        :scope-hours="scopeHours"
      />

      <TurnStatsPanel
        v-if="selectedProviderId"
        :provider-id="selectedProviderId"
        :provider-stats="stats?.turn_stats?.providers?.[selectedProviderId] || null"
      />

      <div class="tool-section-title">Tools</div>
      <div class="tool-summary-list">
        <div v-for="tool in providerTools" :key="tool.tool_name" class="tool-summary-row">
          <div>
            <strong>{{ tool.tool_name }}</strong>
            <span>{{ shortText(tool.last_result_preview) }}</span>
          </div>
          <div class="tool-summary-counts">
            <span>{{ tool.success }} / {{ tool.total }}</span>
            <small :class="{ bad: tool.failure > 0 }">{{ tool.last_status }}</small>
          </div>
        </div>
        <div v-if="selectedProvider && !providerTools.length" class="tool-stats-empty">No tools</div>
      </div>

      <div class="tool-section-title">
        Recent Calls
        <span v-if="selectedProvider">{{ providerFailureCalls.length }} failures in recent records</span>
      </div>
      <div class="recent-call-list">
        <button
          v-for="call in providerRecentCalls"
          :key="callKey(call)"
          type="button"
          class="recent-call-row"
          :class="{ selected: callKey(call) === selectedCallKey, failed: !call.success }"
          @click="selectCall(call)"
        >
          <div class="recent-call-main">
            <strong>{{ call.tool_name }}</strong>
            <span>{{ call.provider_id }} / {{ shortText(call.node_id) }}</span>
            <small>{{ !call.success && call.error ? call.error : shortText(call.result_preview) }}</small>
          </div>
          <div class="recent-call-meta">
            <span :class="{ bad: !call.success }">{{ statusLabel(call) }}</span>
            <small>{{ call.duration_ms ?? '-' }} ms</small>
            <small>{{ call.recorded_at }}</small>
          </div>
        </button>
        <div v-if="!providerRecentCalls.length && !loading" class="tool-stats-empty">No recent calls for this provider</div>
      </div>

      <section v-if="selectedCall" class="call-review" :class="{ failed: !selectedCall.success }">
        <div class="call-review-head">
          <div>
            <div class="tool-section-title">{{ selectedCall.success ? 'Call Review' : 'Failure Review' }}</div>
            <h3>{{ selectedCall.tool_name }}</h3>
          </div>
          <span class="call-review-status" :class="{ bad: !selectedCall.success }">{{ statusLabel(selectedCall) }}</span>
        </div>

        <dl class="call-review-meta">
          <div><dt>Provider</dt><dd>{{ selectedCall.provider_id }}</dd></div>
          <div><dt>Graph / Node</dt><dd>{{ shortText(selectedCall.graph_id) }} / {{ shortText(selectedCall.node_id) }}</dd></div>
          <div><dt>Call ID</dt><dd>{{ shortText(selectedCall.call_id) }}</dd></div>
          <div><dt>Recorded</dt><dd>{{ selectedCall.recorded_at }}</dd></div>
        </dl>

        <div class="call-review-grid">
          <article>
            <h4>{{ invocationLabel(selectedCall) }}</h4>
            <pre>{{ invocationText(selectedCall) }}</pre>
          </article>
          <article :class="{ failure: !selectedCall.success }">
            <h4>Failure reason</h4>
            <pre>{{ failureReason(selectedCall) }}</pre>
          </article>
        </div>

        <article class="call-result">
          <h4>Complete tool result</h4>
          <pre>{{ formatStructuredValue(selectedCall.result, shortText(selectedCall.result_preview)) }}</pre>
        </article>

        <article v-if="selectedCall.diagnostics?.length" class="call-result diagnostics">
          <h4>Diagnostics</h4>
          <pre>{{ selectedCall.diagnostics.join('\n') }}</pre>
        </article>
      </section>

      <div v-if="operationStatus" class="tool-stats-status">{{ operationStatus }}</div>
      <div v-if="error" class="tool-stats-error">{{ error }}</div>
    </section>
  </div>
</template>

<style scoped src="./ToolStatsSettingsPanel.css"></style>
