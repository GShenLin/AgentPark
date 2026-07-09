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

const stats = ref<ToolStatsDocument | null>(null)
const selectedProviderId = ref('')
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
const totalCalls = computed(() => providers.value.reduce((sum, provider) => sum + provider.total, 0))
const successCalls = computed(() => providers.value.reduce((sum, provider) => sum + provider.success, 0))
const failureCalls = computed(() => providers.value.reduce((sum, provider) => sum + provider.failure, 0))
const successRate = computed(() => {
  if (!totalCalls.value) return '0%'
  return `${Math.round((successCalls.value / totalCalls.value) * 100)}%`
})

function selectProvider(providerId: string) {
  selectedProviderId.value = providerId
}

function shortText(value: string, fallback = '-') {
  const text = String(value || '').trim()
  return text || fallback
}

function statusLabel(call: ToolCallStatRecord) {
  return call.success ? 'success' : shortText(call.status, 'failed')
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
          <h2>{{ selectedProvider?.provider_id || 'Tool Static' }}</h2>
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

      <div class="tool-section-title">Recent Calls</div>
      <div class="recent-call-list">
        <div v-for="call in recentCalls" :key="`${call.recorded_at}-${call.call_id}`" class="recent-call-row">
          <div class="recent-call-main">
            <strong>{{ call.tool_name }}</strong>
            <span>{{ call.provider_id }} / {{ shortText(call.node_id) }}</span>
            <small>{{ shortText(call.result_preview) }}</small>
          </div>
          <div class="recent-call-meta">
            <span :class="{ bad: !call.success }">{{ statusLabel(call) }}</span>
            <small>{{ call.duration_ms ?? '-' }} ms</small>
            <small>{{ call.recorded_at }}</small>
          </div>
        </div>
        <div v-if="!recentCalls.length && !loading" class="tool-stats-empty">No recent calls</div>
      </div>

      <div v-if="operationStatus" class="tool-stats-status">{{ operationStatus }}</div>
      <div v-if="error" class="tool-stats-error">{{ error }}</div>
    </section>
  </div>
</template>

<style scoped>
.tool-stats {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  background: var(--bg-primary);
}

.tool-stats-side {
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  border-right: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
}

.tool-stats-action,
.tool-provider-item {
  width: 100%;
  min-height: 36px;
  border-radius: 6px;
}

.tool-stats-action.danger {
  border-color: rgba(239, 68, 68, 0.32);
  color: #fca5a5;
}

.tool-provider-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid transparent;
  background: transparent;
  padding: 8px 10px;
  color: var(--text-secondary);
  text-align: left;
}

.tool-provider-item.active {
  border-color: rgba(59, 130, 246, 0.28);
  background: var(--accent-blue-soft);
  color: var(--text-primary);
}

.tool-provider-item span,
.recent-call-main strong,
.tool-summary-row strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-provider-item small {
  flex: 0 0 auto;
  color: var(--text-tertiary);
}

.tool-stats-main {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
}

.tool-stats-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.tool-stats-head h2 {
  margin: 0;
  font-size: 18px;
  color: var(--text-primary);
}

.tool-stats-head span,
.provider-summary-line span,
.tool-summary-row span,
.recent-call-main span,
.recent-call-main small,
.recent-call-meta small {
  color: var(--text-tertiary);
  font-size: 12px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 10px;
}

.metric-item {
  min-height: 72px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px;
  background: var(--bg-secondary);
}

.metric-item span,
.tool-section-title {
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

.metric-item strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
  color: var(--text-primary);
}

.provider-summary-line {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 36px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-primary);
}

.tool-summary-list,
.recent-call-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tool-summary-row,
.recent-call-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  min-height: 64px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--bg-secondary);
}

.tool-summary-row > div:first-child,
.recent-call-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tool-summary-counts,
.recent-call-meta {
  display: flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 4px;
  color: var(--text-secondary);
}

.tool-summary-counts small,
.recent-call-meta span {
  color: #86efac;
  font-size: 12px;
}

.tool-summary-counts small.bad,
.recent-call-meta span.bad {
  color: #fca5a5;
}

.tool-stats-empty,
.tool-stats-error,
.tool-stats-status {
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  color: var(--text-tertiary);
  background: var(--bg-secondary);
}

.tool-stats-status {
  white-space: pre-wrap;
  color: var(--text-secondary);
}

.tool-stats-error {
  border-color: rgba(239, 68, 68, 0.25);
  color: #fca5a5;
  background: rgba(127, 29, 29, 0.24);
}

@media (max-width: 960px) {
  .tool-stats {
    grid-template-columns: 1fr;
  }

  .tool-stats-side {
    flex-direction: row;
    border-right: none;
    border-bottom: 1px solid var(--border-subtle);
  }

  .tool-stats-action,
  .tool-provider-item {
    width: auto;
    flex: 0 0 auto;
  }

  .metric-grid {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }

  .tool-summary-row,
  .recent-call-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .tool-summary-counts,
  .recent-call-meta {
    align-items: flex-start;
  }
}
</style>
