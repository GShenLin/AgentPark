<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  getProviderLimitTestJob,
  getProviderLimits,
  startProviderLimitTests,
  startProviderModelDiscovery,
  type ProviderLimitDocument,
  type ProviderLimitChannelEntry,
  type ProviderLimitEntry,
  type ProviderLimitTestJob,
} from '../../settingsApi'

const limits = ref<ProviderLimitDocument | null>(null)
const selectedProviderId = ref('')
const loading = ref(false)
const testing = ref(false)
const modelRefreshing = ref(false)
const error = ref('')
const activeJob = ref<ProviderLimitTestJob | null>(null)
let pollTimer: number | null = null

const providerIds = computed(() => Object.keys(limits.value?.providers || {}))
const selectedProvider = computed<ProviderLimitEntry | null>(() => {
  return limits.value?.providers?.[selectedProviderId.value] || null
})
const selectedModelIds = computed(() => selectedProvider.value?.available_model_ids || [])
const selectedChannelResults = computed<Array<{ channel: string; result: ProviderLimitChannelEntry }>>(() => {
  const provider = selectedProvider.value
  if (!provider) return []
  const channels = provider.channels || {}
  const entries = Object.entries(channels)
  if (entries.length) {
    return entries.map(([channel, result]) => ({ channel, result }))
  }
  return [{ channel: provider.test_channel || 'native', result: provider }]
})
const jobRunning = computed(() => activeJob.value?.status === 'running')
const progressLine = computed(() => {
  if (activeJob.value?.status === 'running') {
    const isModelRefresh = activeJob.value.kind === 'model_refresh'
    return {
      label: isModelRefresh ? 'Getting models' : 'Testing',
      index: activeJob.value.index || 0,
      total: activeJob.value.total || 0,
      providerId: activeJob.value.provider_id || '',
    }
  }
  if (limits.value?.model_refresh_status === 'running') {
    return {
      label: 'Getting models',
      index: limits.value.model_refresh_completed_providers || 0,
      total: limits.value.model_refresh_total_providers || 0,
      providerId: limits.value.model_refresh_current_provider_id || '',
    }
  }
  if (limits.value?.status === 'running') {
    return {
      label: 'ProviderLimit snapshot',
      index: limits.value.completed_providers || 0,
      total: limits.value.total_providers || 0,
      providerId: limits.value.current_provider_id || '',
    }
  }
  return null
})

function unsupportedRows(unsupported: ProviderLimitChannelEntry['unsupported'] | undefined) {
  const rows: Array<{ key: string; value: string }> = []
  for (const [key, value] of Object.entries(unsupported || {})) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [childKey, childValue] of Object.entries(value as Record<string, string>)) {
        rows.push({ key: `${key}.${childKey}`, value: String(childValue || 'not supported') })
      }
    } else {
      rows.push({ key, value: String(value || 'not supported') })
    }
  }
  return rows
}

function updateRunningFlags(job: ProviderLimitTestJob | null) {
  const running = job?.status === 'running'
  testing.value = running && job?.kind !== 'model_refresh'
  modelRefreshing.value = running && job?.kind === 'model_refresh'
}

async function loadLimits() {
  loading.value = true
  error.value = ''
  try {
    const next = await getProviderLimits()
    limits.value = next
    if (!selectedProviderId.value || !next.providers?.[selectedProviderId.value]) {
      selectedProviderId.value = Object.keys(next.providers || {})[0] || ''
    }
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    loading.value = false
  }
}

async function startTesting() {
  testing.value = true
  modelRefreshing.value = false
  error.value = ''
  try {
    const response = await startProviderLimitTests()
    activeJob.value = response.job
    limits.value = response.result
    updateRunningFlags(response.job)
    if (!selectedProviderId.value || !response.result.providers?.[selectedProviderId.value]) {
      selectedProviderId.value = Object.keys(response.result.providers || {})[0] || ''
    }
    if (response.job.status !== 'running') {
      testing.value = false
      return
    }
    schedulePoll()
  } catch (e: any) {
    error.value = String(e?.message || e)
    updateRunningFlags(null)
    clearPoll()
  }
}

async function startModelDiscovery() {
  modelRefreshing.value = true
  testing.value = false
  error.value = ''
  try {
    const response = await startProviderModelDiscovery()
    activeJob.value = response.job
    limits.value = response.result
    updateRunningFlags(response.job)
    if (!selectedProviderId.value || !response.result.providers?.[selectedProviderId.value]) {
      selectedProviderId.value = Object.keys(response.result.providers || {})[0] || ''
    }
    if (response.job.status !== 'running') return
    schedulePoll()
  } catch (e: any) {
    error.value = String(e?.message || e)
    updateRunningFlags(null)
    clearPoll()
  }
}

async function pollJob() {
  const jobId = activeJob.value?.job_id || ''
  if (!jobId) {
    updateRunningFlags(null)
    return
  }
  try {
    const response = await getProviderLimitTestJob(jobId)
    activeJob.value = response.job
    limits.value = response.result
    updateRunningFlags(response.job)
    if (response.job.status === 'running') {
      schedulePoll()
      return
    }
    if (response.job.status === 'failed') {
      error.value = response.job.error || 'Provider testing failed'
    }
  } catch (e: any) {
    error.value = String(e?.message || e)
    activeJob.value = {
      ...(activeJob.value || { job_id: jobId }),
      status: 'failed',
      error: error.value,
    }
    updateRunningFlags(activeJob.value)
  } finally {
    if (activeJob.value?.status !== 'running') {
      clearPoll()
    }
  }
}

function schedulePoll() {
  clearPoll()
  pollTimer = window.setTimeout(() => {
    pollTimer = null
    void pollJob()
  }, 1200)
}

function clearPoll() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function providerState(provider: ProviderLimitEntry | undefined) {
  return provider?.accessible ? 'ok' : 'bad'
}

function providerSubtitle(provider: ProviderLimitEntry | undefined) {
  if (!provider) return ''
  return [provider.type, provider.model].filter(Boolean).join(' / ')
}

function testChannelLabel(channel: string | undefined) {
  if (channel === 'responses') return 'Responses API'
  if (channel === 'chat_completions') return 'Chat Completions'
  if (channel === 'messages') return 'Messages API'
  if (channel === 'generate_content') return 'Generate Content'
  if (channel === 'native') return 'Native API'
  return channel || 'Native API'
}

onMounted(loadLimits)
onUnmounted(clearPoll)
</script>

<template>
  <div class="provider-test">
    <aside class="provider-list">
      <div class="test-actions">
        <button type="button" class="start-btn" :disabled="jobRunning || loading" @click="startTesting">
          {{ testing ? 'Testing...' : 'StartTesting' }}
        </button>
        <button type="button" class="model-btn" :disabled="jobRunning || loading" @click="startModelDiscovery">
          {{ modelRefreshing ? 'Getting...' : 'GetModul' }}
        </button>
        <button type="button" :disabled="loading" @click="loadLimits">Reload</button>
      </div>

      <button
        v-for="providerId in providerIds"
        :key="providerId"
        type="button"
        class="provider-item"
        :class="[providerState(limits?.providers?.[providerId]), { active: selectedProviderId === providerId }]"
        @click="selectedProviderId = providerId"
      >
        <span>{{ providerId }}</span>
        <small>{{ providerSubtitle(limits?.providers?.[providerId]) }}</small>
      </button>

      <div v-if="!providerIds.length && !loading" class="empty-list">No test results</div>
    </aside>

    <section class="provider-detail">
      <div class="detail-head">
        <div>
          <h2>{{ selectedProviderId || 'ProviderLimit' }}</h2>
          <span>{{ limits?.path || '' }}</span>
        </div>
        <div v-if="limits?.generated_at" class="generated-at">{{ limits.generated_at }}</div>
      </div>

      <div v-if="progressLine" class="job-line">
        <strong>{{ progressLine.label }}</strong>
        <span>{{ progressLine.index }} / {{ progressLine.total }}</span>
        <span>{{ progressLine.providerId }}</span>
      </div>

      <template v-if="selectedProvider">
        <div class="status-line" :class="providerState(selectedProvider)">
          <strong>{{ selectedProvider.accessible ? 'Accessible' : 'Unavailable' }}</strong>
          <span>{{ selectedProvider.type }} / {{ selectedProvider.model }}</span>
        </div>

        <div class="channel-results">
          <article
            v-for="channelResult in selectedChannelResults"
            :key="channelResult.channel"
            class="channel-result"
            :class="providerState(channelResult.result)"
          >
            <div class="channel-result-head">
              <strong>{{ testChannelLabel(channelResult.channel) }}</strong>
              <span>{{ channelResult.result.accessible ? 'Accessible' : 'Unavailable' }}</span>
            </div>
            <div class="channel-summary">
              <div v-if="channelResult.result.test_endpoint">
                <span>Endpoint</span>
                <code>{{ channelResult.result.test_endpoint }}</code>
              </div>
              <div v-if="channelResult.result.access_error">
                <span>Access error</span>
                <code>{{ channelResult.result.access_error }}</code>
              </div>
            </div>
            <div v-if="unsupportedRows(channelResult.result.unsupported).length" class="channel-unsupported">
              <div
                v-for="row in unsupportedRows(channelResult.result.unsupported)"
                :key="row.key"
                class="unsupported-row"
              >
                <div class="limit-key">{{ row.key }}</div>
                <div class="limit-value">{{ row.value }}</div>
              </div>
            </div>
            <div v-else class="all-supported">No unsupported tested attributes</div>
          </article>
        </div>

        <div v-if="selectedModelIds.length" class="model-list">
          <div class="model-list-head">
            <strong>Models</strong>
            <span>{{ selectedModelIds.length }}</span>
          </div>
          <div class="model-grid">
            <span v-for="modelId in selectedModelIds" :key="modelId">{{ modelId }}</span>
          </div>
        </div>

      </template>

      <div v-else-if="loading || testing" class="empty-detail">Loading...</div>
      <div v-else class="empty-detail">No provider selected</div>

      <div v-if="error" class="settings-error">{{ error }}</div>
    </section>
  </div>
</template>

<style scoped src="./ProviderTestSettingsPanel.css"></style>
