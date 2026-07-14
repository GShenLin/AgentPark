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
const loading = ref(false)
const clearing = ref(false)
const deletingOptionalMemory = ref(false)
const error = ref('')
const operationStatus = ref('')

const providers = computed<ToolStatsProviderSummary[]>(() => {
  const source = stats.value?.summary?.providers || {}
  return Object.values(source).sort((a, b) => b.total - a.total || a.provider_id.localeCompare(b.provider_id))
})

const selectedProvider = computed<ToolStatsProviderSummary | null>(() => {
  return stats.value?.summary?.providers?.[selectedProviderId.value] || providers.value[0] || null
})

const providerTools = computed(() => {
  const tools = selectedProvider.value?.tools || {}
  return Object.values(tools).sort((a, b) => b.total - a.total || a.tool_name.localeCompare(b.tool_name))
})

const recentCalls = computed<ToolCallStatRecord[]>(() => stats.value?.recent_calls || [])
const providerRecentCalls = computed<ToolCallStatRecord[]>(() => {
  if (!selectedProvider.value) return recentCalls.value
  return recentCalls.value.filter((call) => call.provider_id === selectedProvider.value?.provider_id)
})
const providerFailureCalls = computed(() => providerRecentCalls.value.filter((call) => !call.success))
const failureAnalysis = computed(() => stats.value?.failure_analysis || null)
const selectedCall = computed<ToolCallStatRecord | null>(() => {
  return providerRecentCalls.value.find((call) => callKey(call) === selectedCallKey.value)
    || providerFailureCalls.value[0]
    || providerRecentCalls.value[0]
    || null
})
const totalCalls = computed(() => providers.value.reduce((sum, provider) => sum + provider.total, 0))
const successCalls = computed(() => providers.value.reduce((sum, provider) => sum + provider.success, 0))
const failureCalls = computed(() => providers.value.reduce((sum, provider) => sum + provider.failure, 0))
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
    const next = await getToolStats()
    stats.value = next
    if (!selectedProviderId.value || !next.summary.providers?.[selectedProviderId.value]) {
      selectedProviderId.value = Object.keys(next.summary.providers || {})[0] || ''
    }
    selectDefaultCall(selectedProviderId.value, next.recent_calls || [])
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    loading.value = false
  }
}

async function clearStats() {
  const ok = window.confirm('Clear all tool stats?')
  if (!ok) return
  clearing.value = true
  error.value = ''
  operationStatus.value = ''
  try {
    const next = await clearToolStats()
    stats.value = next
    selectedProviderId.value = ''
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
      <button type="button" class="tool-stats-action danger" :disabled="loading || clearing || deletingOptionalMemory || !totalCalls" @click="clearStats">
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
        v-for="provider in providers"
        :key="provider.provider_id"
        type="button"
        class="tool-provider-item"
        :class="{ active: selectedProviderId === provider.provider_id }"
        @click="selectProvider(provider.provider_id)"
      >
        <span>{{ provider.provider_id }}</span>
        <small>{{ provider.success }} / {{ provider.total }}</small>
      </button>

      <div v-if="!providers.length && !loading" class="tool-stats-empty">No tool stats</div>
    </aside>

    <section class="tool-stats-main">
      <div class="tool-stats-head">
        <div>
          <h2>{{ selectedProvider?.provider_id || 'Tool Statistics' }}</h2>
          <span>{{ stats?.summary.updated_at || '' }}</span>
        </div>
      </div>

      <div class="metric-grid">
        <div class="metric-item">
          <span>Total</span>
          <strong>{{ totalCalls }}</strong>
        </div>
        <div class="metric-item">
          <span>Success</span>
          <strong>{{ successCalls }}</strong>
        </div>
        <div class="metric-item">
          <span>Failure</span>
          <strong>{{ failureCalls }}</strong>
        </div>
        <div class="metric-item">
          <span>Rate</span>
          <strong>{{ successRate }}</strong>
        </div>
      </div>

      <div v-if="selectedProvider" class="provider-summary-line">
        <strong>{{ selectedProvider.success }} success</strong>
        <span>{{ selectedProvider.failure }} failure</span>
        <span>{{ selectedProvider.last_call_at }}</span>
      </div>

      <ToolFailurePatternsPanel v-if="failureAnalysis?.total_failures" :analysis="failureAnalysis" />

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
