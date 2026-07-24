<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getProviderPressure, type ProviderPressureDocument, type ProviderPressureEntry } from '../../settingsApi'

const pressure = ref<ProviderPressureDocument | null>(null)
const loading = ref(false)
const error = ref('')
let refreshTimer: number | undefined

const providers = computed<ProviderPressureEntry[]>(() => {
  return (pressure.value?.providers || []).slice().sort((a, b) => {
    const loadDiff = (b.queued + b.in_flight) - (a.queued + a.in_flight)
    return loadDiff || a.provider_id.localeCompare(b.provider_id)
  })
})

function limitText(value: number | null | undefined) {
  return value == null ? '∞' : String(value)
}

function currentPeakText(current: number, peak: number) {
  return `${current} / ${Math.max(current, peak || 0)}`
}

function secondsText(value: number | null | undefined) {
  if (value == null) return '∞'
  if (value <= 0) return '0s'
  if (value < 1) return `${Math.round(value * 1000)}ms`
  return `${value.toFixed(1)}s`
}

function tokenText(value: number | null | undefined) {
  if (value == null) return '∞'
  return Math.max(0, value).toLocaleString()
}

function pressureClass(provider: ProviderPressureEntry) {
  if (provider.queued > 0) return 'queued'
  if (provider.in_flight > 0) return 'active'
  return ''
}

async function refreshPressure() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    pressure.value = await getProviderPressure()
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  refreshPressure()
  refreshTimer = window.setInterval(refreshPressure, 1500)
})

onUnmounted(() => {
  if (refreshTimer !== undefined) {
    window.clearInterval(refreshTimer)
  }
})
</script>

<template>
  <section class="pressure-panel">
    <div class="pressure-toolbar">
      <div class="pressure-title">
        <h2>Provider Pressure</h2>
        <span>{{ providers.length }} providers</span>
      </div>
      <button type="button" :disabled="loading" @click="refreshPressure">{{ loading ? 'Refreshing...' : 'Refresh' }}</button>
    </div>

    <div class="pressure-table-wrap">
      <table class="pressure-table">
        <thead>
          <tr>
            <th>Provider</th>
            <th>Type</th>
            <th>Model</th>
            <th>Concurrency</th>
            <th>Queue</th>
            <th>RPM Limit</th>
            <th>Interval</th>
            <th>Next</th>
            <th>Total TPM</th>
            <th>Input TPM</th>
            <th>Output TPM</th>
            <th>TPM Next</th>
            <th>Peak</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="provider in providers" :key="provider.provider_id" :class="pressureClass(provider)">
            <td class="provider-id">{{ provider.provider_id }}</td>
            <td>{{ provider.type || '-' }}</td>
            <td class="model-cell">{{ provider.model || '-' }}</td>
            <td>{{ provider.in_flight }} / {{ limitText(provider.concurrency_limit) }}</td>
            <td>{{ currentPeakText(provider.queued, provider.peak_queued) }}</td>
            <td>{{ limitText(provider.rpm_limit) }}</td>
            <td>{{ secondsText(provider.rpm_interval_sec) }}</td>
            <td>{{ secondsText(provider.rpm_next_available_in_sec) }}</td>
            <td>
              {{ tokenText(provider.tpm_used) }} / {{ tokenText(provider.tpm_limit) }}
              <small>left {{ tokenText(provider.tpm_remaining) }}</small>
            </td>
            <td>{{ tokenText(provider.input_tpm_used) }}</td>
            <td>{{ tokenText(provider.output_tpm_used) }}</td>
            <td>{{ secondsText(provider.tpm_next_available_in_sec) }}</td>
            <td class="peak-cell">
              <span>C {{ provider.peak_in_flight }}</span>
              <span>Q {{ provider.peak_queued }}</span>
              <span>R {{ provider.peak_rpm_used }}</span>
              <span>T {{ tokenText(provider.peak_tpm_used) }}</span>
              <span>TI {{ tokenText(provider.peak_input_tpm_used) }}</span>
              <span>TO {{ tokenText(provider.peak_output_tpm_used) }}</span>
            </td>
          </tr>
          <tr v-if="!providers.length && !loading">
            <td colspan="13" class="empty-cell">No providers</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="error" class="pressure-error">{{ error }}</div>
  </section>
</template>

<style scoped>
.pressure-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.pressure-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pressure-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.pressure-title h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
}

.pressure-title span {
  color: var(--text-muted, #6b7280);
  font-size: 12px;
}

.pressure-toolbar button {
  border: 1px solid var(--border, #d1d5db);
  background: var(--surface, #fff);
  color: var(--text, #111827);
  border-radius: 6px;
  padding: 7px 12px;
  cursor: pointer;
}

.pressure-toolbar button:disabled {
  cursor: default;
  opacity: 0.65;
}

.pressure-table-wrap {
  overflow: auto;
  border: 1px solid var(--border, #d1d5db);
  border-radius: 8px;
}

.pressure-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 1380px;
  font-size: 13px;
}

.pressure-table th,
.pressure-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-subtle, #e5e7eb);
  text-align: left;
  white-space: nowrap;
}

.pressure-table th {
  background: var(--surface-subtle, #f9fafb);
  color: var(--text-muted, #6b7280);
  font-size: 12px;
  font-weight: 650;
}

.pressure-table tbody tr:last-child td {
  border-bottom: 0;
}

.pressure-table tr.active td {
  background: rgba(37, 99, 235, 0.06);
}

.pressure-table tr.queued td {
  background: rgba(217, 119, 6, 0.08);
}

.provider-id {
  font-weight: 650;
}

.model-cell {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.peak-cell {
  display: flex;
  gap: 8px;
}

.peak-cell span {
  color: var(--text-muted, #6b7280);
}

.pressure-table td small {
  display: block;
  margin-top: 2px;
  color: var(--text-muted, #6b7280);
  font-size: 11px;
}

.empty-cell {
  color: var(--text-muted, #6b7280);
  text-align: center;
}

.pressure-error {
  color: #b91c1c;
  font-size: 13px;
}
</style>
