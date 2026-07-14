<script setup lang="ts">
import { computed } from 'vue'
import ResponseToolInsights from './ResponseToolInsights.vue'

const props = defineProps<{ data: unknown }>()

type Source = { url: string; title?: string; type?: string }

const payload = computed<Record<string, any>>(() => (
  props.data && typeof props.data === 'object' ? props.data as Record<string, any> : {}
))

const metadata = computed<Record<string, any>>(() => (
  payload.value.response_metadata && typeof payload.value.response_metadata === 'object'
    ? payload.value.response_metadata
    : {}
))

const response = computed<Record<string, any>>(() => (
  metadata.value.response && typeof metadata.value.response === 'object'
    ? metadata.value.response
    : {}
))

const providerRequests = computed<Record<string, any>>(() => (
  payload.value.provider_requests && typeof payload.value.provider_requests === 'object'
    ? payload.value.provider_requests
    : {}
))

const providerTotals = computed<Record<string, any>>(() => (
  providerRequests.value.totals && typeof providerRequests.value.totals === 'object'
    ? providerRequests.value.totals
    : {}
))

const scope = computed(() => String(payload.value.scope || '').trim())

const heading = computed(() => {
  if (scope.value === 'provider_turn') return 'Provider turn details'
  if (scope.value === 'final_assistant') return 'Final response details'
  if (scope.value === 'agent_run') return 'Agent run details'
  return 'Response details'
})

const sources = computed<Source[]>(() => {
  const values: unknown[] = []
  if (Array.isArray(payload.value.citations)) values.push(...payload.value.citations)
  if (Array.isArray(payload.value.server_tool_calls)) {
    for (const call of payload.value.server_tool_calls) {
      if (call && typeof call === 'object' && Array.isArray(call.sources)) values.push(...call.sources)
    }
  }
  const seen = new Set<string>()
  const output: Source[] = []
  for (const value of values) {
    if (!value || typeof value !== 'object') continue
    const item = value as Record<string, unknown>
    const url = String(item.url || '').trim()
    if (!/^https?:\/\//i.test(url) || seen.has(url)) continue
    seen.add(url)
    output.push({
      url,
      title: String(item.title || '').trim() || undefined,
      type: String(item.type || '').trim() || undefined,
    })
  }
  return output
})

const summary = computed(() => {
  const chunks: string[] = []
  const status = String(response.value.status || '').trim()
  const model = String(response.value.model || '').trim()
  const responseId = String(response.value.id || '').trim()
  if (status) chunks.push(status)
  if (model) chunks.push(model)
  if (responseId) chunks.push(responseId)
  return chunks.join(' / ')
})

const usage = computed(() => {
  const value = response.value.usage
  if (!value || typeof value !== 'object') return ''
  const input = Number((value as any).input_tokens)
  const output = Number((value as any).output_tokens)
  const total = Number((value as any).total_tokens)
  const chunks: string[] = []
  if (Number.isFinite(input)) chunks.push(`input ${input}`)
  if (Number.isFinite(output)) chunks.push(`output ${output}`)
  if (Number.isFinite(total)) chunks.push(`total ${total}`)
  return chunks.join(' / ')
})

const totalUsage = computed(() => {
  const fields: Array<[string, string]> = [
    ['actual_input_tokens', 'input'],
    ['actual_cached_input_tokens', 'cached'],
    ['actual_cache_write_input_tokens', 'cache write'],
    ['actual_output_tokens', 'output'],
    ['actual_reasoning_output_tokens', 'reasoning'],
    ['actual_total_tokens', 'total'],
  ]
  const chunks: string[] = []
  for (const [key, label] of fields) {
    const value = Number(providerTotals.value[key])
    if (Number.isFinite(value)) chunks.push(`${label} ${value.toLocaleString()}`)
  }
  const completed = Number(providerTotals.value.completed_request_count)
  if (Number.isFinite(completed)) chunks.push(`${completed} requests`)
  return chunks.join(' / ')
})
</script>

<template>
  <section class="response-metadata">
    <div class="response-metadata-head">
      <strong>{{ heading }}</strong>
      <span v-if="summary">{{ summary }}</span>
    </div>
    <div v-if="totalUsage" class="response-usage">Full-turn usage: {{ totalUsage }}</div>
    <div v-else-if="usage" class="response-usage">Last response tokens: {{ usage }}</div>
    <details v-if="sources.length" class="response-category">
      <summary>Referenced web pages ({{ sources.length }})</summary>
      <div class="response-sources">
        <a
          v-for="source in sources"
          :key="source.url"
          class="response-source"
          :href="source.url"
          target="_blank"
          rel="noreferrer noopener"
        >
          <span>{{ source.title || source.url }}</span>
          <small v-if="source.title">{{ source.url }}</small>
        </a>
      </div>
    </details>
    <ResponseToolInsights :metadata="metadata" />
    <details v-if="Object.keys(metadata).length" class="response-raw">
      <summary>{{ scope === 'provider_turn' ? 'Provider response for this turn' : 'Provider response payload' }}</summary>
      <pre>{{ JSON.stringify(metadata, null, 2) }}</pre>
    </details>
  </section>
</template>

<style scoped>
.response-metadata {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 9px;
  border: 1px solid rgba(56, 189, 248, 0.24);
  border-radius: 8px;
  background: rgba(8, 47, 73, 0.16);
  min-width: 0;
}

.response-category,
.response-raw {
  min-width: 0;
}

.response-category[open] > summary,
.response-raw[open] > summary {
  position: sticky;
  top: 0;
  z-index: 30;
  margin: 0 -4px;
  padding: 5px 4px;
  border-radius: 5px;
  background: rgba(9, 38, 57, 0.98);
  box-shadow: 0 4px 8px rgba(2, 6, 23, 0.22);
}

.response-metadata-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: rgba(226, 232, 240, 0.92);
  font-size: 12px;
}

.response-metadata-head span,
.response-usage {
  color: rgba(148, 163, 184, 0.9);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.response-sources {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 6px;
}

.response-category summary {
  cursor: pointer;
  color: rgba(186, 230, 253, 0.9);
  font-size: 11px;
  font-weight: 700;
}

.response-source {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 7px;
  border-radius: 6px;
  color: rgba(125, 211, 252, 0.96);
  background: rgba(2, 132, 199, 0.09);
  text-decoration: none;
  overflow-wrap: anywhere;
  font-size: 11px;
}

.response-source:hover {
  background: rgba(2, 132, 199, 0.18);
}

.response-source small {
  color: rgba(148, 163, 184, 0.82);
}

.response-raw summary {
  cursor: pointer;
  color: rgba(203, 213, 225, 0.84);
  font-size: 11px;
}

.response-raw pre {
  max-height: 360px;
  margin: 7px 0 0;
  padding: 8px;
  overflow: auto;
  border-radius: 7px;
  background: rgba(2, 6, 23, 0.48);
  color: rgba(203, 213, 225, 0.9);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 10px;
}
</style>
