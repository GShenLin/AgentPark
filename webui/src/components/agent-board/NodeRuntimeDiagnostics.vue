<script setup lang="ts">
import { computed } from 'vue'
import type { ProviderRequestSummary, RuntimeEvent, RuntimeToolCall } from '../../api'
import {
  latestRuntimeNotice,
  normalizeRuntimeEvents,
} from './toolRuntimeEvents'

const props = defineProps<{
  events?: RuntimeEvent[]
  providerSummaries?: ProviderRequestSummary[]
  runtimeToolCalls?: RuntimeToolCall[]
}>()

type DiagnosticRow = {
  label: string
  value: string
  tone?: 'attention' | 'ok' | 'muted'
}

const runtimeEvents = computed(() => normalizeRuntimeEvents(props.events))
const providerSummaries = computed(() => Array.isArray(props.providerSummaries) ? props.providerSummaries as Record<string, unknown>[] : [])
const latestNotice = computed(() => latestRuntimeNotice(runtimeEvents.value))
const latestNoticePayload = computed(() => parseJsonObject(latestNotice.value?.message))
const latestProviderSummary = computed(() => providerSummaries.value[providerSummaries.value.length - 1] || null)
const runtimeToolCallCount = computed(() => Array.isArray(props.runtimeToolCalls) ? props.runtimeToolCalls.length : null)

const hasDiagnostics = computed(() => {
  return !!latestNotice.value || !!latestProviderSummary.value
})

const noticeRows = computed<DiagnosticRow[]>(() => {
  const notice = latestNotice.value
  if (!notice) return []
  const payload = latestNoticePayload.value
  const rows: DiagnosticRow[] = []
  const tool = stringField(payload, 'tool') || String(notice.name || '').trim()
  if (tool) rows.push({ label: 'Tool', value: tool })
  const policy = stringField(payload, 'policy')
  if (policy) rows.push({ label: 'Policy', value: policy })
  return rows
})

const requestRows = computed<DiagnosticRow[]>(() => {
  const summary = latestProviderSummary.value
  if (!summary) return []
  const rows: DiagnosticRow[] = []
  const inputItems = numberField(summary, 'input_item_count')
  const approxChars = numberField(summary, 'approx_input_chars')
  const approxTokens = numberField(summary, 'approx_input_tokens')
  const environmentChars = numberField(summary, 'environment_context_chars')
  if (approxTokens != null || inputItems != null || approxChars != null) {
    rows.push({
      label: 'Context',
      value: formatContext(approxTokens, approxChars, inputItems),
    })
  }
  if (environmentChars != null && environmentChars > 0) {
    rows.push({ label: 'Env', value: formatChars(environmentChars), tone: 'muted' })
  }
  const largestToolResult = summary.largest_tool_result
  if (largestToolResult && typeof largestToolResult === 'object') {
    const item = largestToolResult as Record<string, unknown>
    const name = stringField(item, 'name')
    const callId = stringField(item, 'call_id')
    const chars = numberField(item, 'chars')
    rows.push({
      label: 'Largest Tool',
      value: `${name || callId || 'tool'}${chars != null ? ` / ${formatChars(chars)}` : ''}`,
      tone: chars != null && chars > 50000 ? 'attention' : 'muted',
    })
  }
  const toolsCount = numberField(summary, 'tools_included_count')
  if (toolsCount != null) rows.push({ label: 'Tools Sent', value: String(toolsCount) })
  const toolResultCount = Array.isArray(summary.tool_result_chars_by_call) ? summary.tool_result_chars_by_call.length : null
  if (toolResultCount != null || runtimeToolCallCount.value != null) {
    const parts: string[] = []
    if (toolResultCount != null) parts.push(`${toolResultCount} results`)
    if (runtimeToolCallCount.value != null) parts.push(`${runtimeToolCallCount.value} runtime`)
    rows.push({ label: 'Tool Calls', value: parts.join(' / ') })
  }
  return rows
})

function parseJsonObject(value: unknown): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(String(value || ''))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null
  } catch {
    return null
  }
}

function stringField(source: Record<string, unknown> | null, key: string) {
  const value = source?.[key]
  return value == null ? '' : String(value).trim()
}

function numberField(source: Record<string, unknown> | null, key: string) {
  const value = source?.[key]
  if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, Math.round(value))
  return null
}

function formatChars(value: number) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M chars`
  if (value >= 1000) return `${Math.round(value / 1000)}k chars`
  return `${value} chars`
}

function formatTokens(value: number) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M tokens`
  if (value >= 1000) return `${Math.round(value / 1000)}k tokens`
  return `${value} tokens`
}

function formatContext(tokens: number | null, chars: number | null, inputItems: number | null) {
  const parts: string[] = []
  if (tokens != null) parts.push(formatTokens(tokens))
  if (chars != null) parts.push(formatChars(chars))
  if (!parts.length) parts.push(`${inputItems ?? 0} input entries`)
  return parts.join(' / ')
}

</script>

<template>
  <div v-if="hasDiagnostics" class="runtime-diagnostics">
    <div v-if="noticeRows.length" class="runtime-group">
      <div v-for="row in noticeRows" :key="`notice-${row.label}`" class="runtime-row" :class="row.tone ? `tone-${row.tone}` : ''">
        <span class="runtime-label">{{ row.label }}</span>
        <span class="runtime-value">{{ row.value }}</span>
      </div>
    </div>
    <div v-if="requestRows.length" class="runtime-group">
      <div v-for="row in requestRows" :key="`request-${row.label}`" class="runtime-row" :class="row.tone ? `tone-${row.tone}` : ''">
        <span class="runtime-label">{{ row.label }}</span>
        <span class="runtime-value">{{ row.value }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.runtime-diagnostics {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 7px;
  padding: 5px 6px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.36);
}

.runtime-group {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.runtime-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  min-width: 0;
  font-size: 10px;
  line-height: 1.3;
  color: rgba(226, 232, 240, 0.86);
}

.runtime-label {
  flex: 0 0 auto;
  color: rgba(148, 163, 184, 0.9);
}

.runtime-label::after {
  content: ':';
}

.runtime-value {
  min-width: 0;
  flex: 1 1 auto;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tone-attention .runtime-value {
  color: #fbbf24;
}

.tone-ok .runtime-value,
.tone-done .runtime-value {
  color: #34d399;
}

.tone-running .runtime-value {
  color: #7dd3fc;
}

.tone-muted .runtime-value {
  color: rgba(203, 213, 225, 0.82);
}
</style>
