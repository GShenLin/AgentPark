<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getGatewayUsage, type GatewayUsageStats } from '../../gatewayApi'
import { t } from '../../i18n'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'

const selectedDate = ref(localDateText())
const stats = ref<GatewayUsageStats | null>(null)
const loading = ref(false)
const error = ref('')

function localDateText() {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatTokens(value: number) {
  return new Intl.NumberFormat().format(value)
}

async function loadUsage() {
  if (!selectedDate.value) return
  loading.value = true
  error.value = ''
  try {
    stats.value = await getGatewayUsage(selectedDate.value)
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    loading.value = false
  }
}

onMounted(loadUsage)
</script>

<template>
  <section class="gateway-card gateway-usage-card">
    <div class="usage-head">
      <div>
        <h2>{{ t('gateway.usageTitle') }}</h2>
        <p>{{ t('gateway.usageHelp') }}</p>
      </div>
      <div class="date-filter">
        <FormTextInput v-model="selectedDate" type="date" compact @change="loadUsage" />
        <ActionButton compact :disabled="loading" @click="loadUsage">
          {{ t('settings.reload') }}
        </ActionButton>
      </div>
    </div>

    <div v-if="stats" class="usage-summary">
      <div><span>{{ t('gateway.usageTotal') }}</span><strong>{{ formatTokens(stats.totals.totalTokens) }}</strong></div>
      <div><span>{{ t('gateway.usageInput') }}</span><strong>{{ formatTokens(stats.totals.inputTokens) }}</strong></div>
      <div><span>{{ t('gateway.usageOutput') }}</span><strong>{{ formatTokens(stats.totals.outputTokens) }}</strong></div>
      <div><span>{{ t('gateway.usageRequests') }}</span><strong>{{ formatTokens(stats.totals.requestCount) }}</strong></div>
    </div>

    <div v-if="stats?.totals.missingUsageRequestCount" class="usage-warning">
      {{ t('gateway.usageMissing', { count: stats.totals.missingUsageRequestCount }) }}
    </div>

    <div v-if="stats?.ips.length" class="usage-ip-list">
      <article v-for="entry in stats.ips" :key="entry.ip" class="usage-ip-card">
        <header>
          <code>{{ entry.ip }}</code>
          <span>{{ formatTokens(entry.totalTokens) }} {{ t('gateway.usageTokens') }} · {{ formatTokens(entry.requestCount) }} {{ t('gateway.usageRequestUnit') }}</span>
        </header>
        <div class="usage-table-wrap">
          <table>
            <thead>
              <tr>
                <th>{{ t('gateway.usageModel') }}</th>
                <th>{{ t('gateway.usageRequests') }}</th>
                <th>{{ t('gateway.usageInput') }}</th>
                <th>{{ t('gateway.usageOutput') }}</th>
                <th>{{ t('gateway.usageTotal') }}</th>
                <th>{{ t('gateway.usageCached') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="model in entry.models" :key="model.modelId">
                <td><code>{{ model.modelId }}</code></td>
                <td>{{ formatTokens(model.requestCount) }}</td>
                <td>{{ formatTokens(model.inputTokens) }}</td>
                <td>{{ formatTokens(model.outputTokens) }}</td>
                <td>{{ formatTokens(model.totalTokens) }}</td>
                <td>{{ formatTokens(model.cachedInputTokens) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>

    <p v-else-if="stats && !loading" class="usage-empty">{{ t('gateway.usageEmpty') }}</p>
    <div v-if="error" class="usage-error">{{ error }}</div>
  </section>
</template>

<style scoped src="./GatewayUsagePanel.css"></style>
