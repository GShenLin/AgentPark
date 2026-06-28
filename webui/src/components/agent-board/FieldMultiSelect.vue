<script setup lang="ts">
import { computed } from 'vue'
import FieldMultiSelectOption from './FieldMultiSelectOption.vue'

type OptionItem = {
  value: string
  label: string
  kind?: string
  description?: string
  source?: string
  enabled?: boolean
  status?: string
  diagnostics?: string[]
  dependencies?: Array<{ kind: string; id: string }>
  effective?: string
}

type DisplayOption = OptionItem & {
  title: string
  description: string
  meta: string
  sourceLabel: string
  statusLabel: string
  statusClass: string
  dependencySummary: string
  diagnosticLines: string[]
  nextRunLabel: string
}

const props = defineProps<{
  label: string
  options: OptionItem[]
  selectedValues: string[]
  emptyText: string
  searchQuery?: string
}>()

const emit = defineEmits<{
  toggle: [value: string]
}>()

const selectedSet = computed(() => new Set(props.selectedValues.map((value) => String(value || '').trim()).filter(Boolean)))
const searchText = computed(() => String(props.searchQuery || '').trim().toLowerCase())
const hasSearch = computed(() => searchText.value.length > 0)
const itemName = computed(() => {
  const emptyText = props.emptyText.toLowerCase()
  if (emptyText.includes('skill')) return 'skills'
  if (emptyText.includes('tool')) return 'tools'
  if (emptyText.includes('plugin')) return 'plugins'
  if (emptyText.includes('mcp')) return 'MCP servers'
  return 'items'
})

const displayOptions = computed(() => {
  const seen = new Set<string>()
  const normalized = props.options
    .map((option) => normalizeOption(option))
    .filter((option) => {
      if (!option.value || seen.has(option.value)) return false
      seen.add(option.value)
      return true
    })

  props.selectedValues.forEach((value) => {
    const selectedValue = String(value || '').trim()
    if (!selectedValue || seen.has(selectedValue)) return
    seen.add(selectedValue)
    normalized.push(normalizeOption({ value: selectedValue, label: selectedValue }))
  })

  return normalized
})

const selectedOptions = computed(() =>
  displayOptions.value
    .filter((option) => selectedSet.value.has(option.value))
    .sort(compareOptions),
)

const availableOptions = computed(() =>
  displayOptions.value
    .filter((option) => !selectedSet.value.has(option.value))
    .sort(compareOptions),
)

const visibleSelectedOptions = computed(() => selectedOptions.value.filter(matchesSearch))
const visibleAvailableOptions = computed(() => availableOptions.value.filter(matchesSearch))
const visibleOptionCount = computed(() => visibleSelectedOptions.value.length + visibleAvailableOptions.value.length)

function compareOptions(a: DisplayOption, b: DisplayOption) {
  return a.title.localeCompare(b.title)
}

function matchesSearch(option: DisplayOption) {
  if (!searchText.value) return true
  const haystack = [
    option.title,
    option.description,
    option.meta,
    option.sourceLabel,
    option.statusLabel,
    option.dependencySummary,
    option.diagnosticLines.join(' '),
    option.nextRunLabel,
    option.value,
    option.label,
  ].join(' ').toLowerCase()
  return haystack.includes(searchText.value)
}

function normalizeOption(option: OptionItem): DisplayOption {
  const value = String(option.value || '').trim()
  const label = String(option.label || value).trim()
  const { title, description: labelDescription } = splitLabel(label, value)
  const description = String(option.description || '').trim() || labelDescription
  const meta = shouldShowMeta(value, title, description) ? value : ''
  const status = String(option.status || '').trim()
  const isDraftSelected = selectedSet.value.has(value)
  const hasPersistedEnabled = typeof option.enabled === 'boolean'
  const nextRunLabel =
    option.effective === 'next_agent_run' && hasPersistedEnabled && option.enabled !== isDraftSelected
      ? (isDraftSelected ? 'enables next run' : 'disables next run')
      : ''
  return {
    ...option,
    value,
    label,
    title,
    description,
    meta,
    sourceLabel: normalizeBadgeText(option.source),
    statusLabel: normalizeBadgeText(status),
    statusClass: normalizeStatusClass(status),
    dependencySummary: summarizeDependencies(option.dependencies),
    diagnosticLines: normalizeStringList(option.diagnostics).slice(0, 3),
    nextRunLabel,
  }
}

function splitLabel(label: string, value: string) {
  const separator = [' - ', ' — ', ' – '].find((token) => label.includes(token))
  if (separator) {
    const [rawTitle, ...rest] = label.split(separator)
    return {
      title: cleanTitle(rawTitle || value),
      description: rest.join(separator).trim(),
    }
  }

  const title = cleanTitle(label || value)
  return {
    title,
    description: '',
  }
}

function cleanTitle(text: string) {
  const trimmed = String(text || '').trim()
  if (!trimmed) return 'Untitled'
  const normalized = trimmed.replace(/\\/g, '/').replace(/\/+$/g, '')
  if (!normalized.includes('/') && !normalized.startsWith('.')) return normalized
  const lastPart = normalized.split('/').filter(Boolean).pop() || normalized
  return lastPart.replace(/\.py$/i, '') || normalized
}

function shouldShowMeta(value: string, title: string, description: string) {
  if (!value || description) return false
  return value !== title && (value.includes('/') || value.includes('\\'))
}

function normalizeBadgeText(value: unknown) {
  return String(value || '').trim().replace(/_/g, ' ')
}

function normalizeStatusClass(status: string) {
  const normalized = String(status || '').trim().toLowerCase()
  if (normalized === 'error') return 'is-error'
  if (normalized === 'unavailable') return 'is-unavailable'
  if (normalized === 'selected') return 'is-selected-status'
  return ''
}

function normalizeStringList(value: unknown) {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item || '').trim()).filter(Boolean)
}

function summarizeDependencies(value: unknown) {
  if (!Array.isArray(value) || value.length === 0) return ''
  const counts = new Map<string, number>()
  for (const item of value) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    const kind = String((item as Record<string, unknown>).kind || '').trim()
    const id = String((item as Record<string, unknown>).id || '').trim()
    if (!kind || !id) continue
    counts.set(kind, (counts.get(kind) || 0) + 1)
  }
  const parts = Array.from(counts.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([kind, count]) => `${count} ${kind}${count === 1 ? '' : 's'}`)
  return parts.length ? `Includes ${parts.join(', ')}` : ''
}
</script>

<template>
  <div class="multi-select-panel">
    <div class="multi-select-status" aria-live="polite">
      <span>{{ selectedOptions.length }} enabled</span>
      <span>{{ displayOptions.length }} total</span>
      <span v-if="hasSearch">{{ visibleOptionCount }} matches</span>
    </div>

    <div v-if="displayOptions.length === 0" class="multi-select-empty">
      {{ emptyText }}
    </div>

    <template v-else>
      <div class="multi-select-group-heading">Enabled</div>
      <div v-if="visibleSelectedOptions.length" class="multi-select-list">
        <FieldMultiSelectOption
          v-for="option in visibleSelectedOptions"
          :key="`selected-option-${option.value}`"
          :option="option"
          selected
          diagnostic-key-prefix="selected-diagnostic"
          @toggle="emit('toggle', $event)"
        />
      </div>
      <div v-else-if="hasSearch && selectedOptions.length" class="multi-select-empty compact">
        No matching enabled {{ itemName }}.
      </div>
      <div v-else class="multi-select-empty compact">
        No {{ itemName }} enabled.
      </div>

      <details class="multi-select-available" :open="hasSearch || selectedOptions.length === 0">
        <summary>
          <span>Available</span>
          <span>{{ hasSearch ? visibleAvailableOptions.length : availableOptions.length }}</span>
        </summary>
        <div class="multi-select-list available-list">
          <FieldMultiSelectOption
            v-for="option in visibleAvailableOptions"
            :key="`available-option-${option.value}`"
            :option="option"
            :selected="false"
            diagnostic-key-prefix="available-diagnostic"
            @toggle="emit('toggle', $event)"
          />
          <div
            v-if="hasSearch && visibleAvailableOptions.length === 0 && availableOptions.length"
            class="multi-select-empty compact"
          >
            No matching available {{ itemName }}.
          </div>
          <div v-else-if="availableOptions.length === 0" class="multi-select-empty compact">
            All {{ itemName }} are enabled.
          </div>
        </div>
      </details>
    </template>
  </div>
</template>

<style scoped>
.multi-select-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.72);
  padding: 8px;
  width: 100%;
  min-width: 0;
}

.multi-select-status,
.multi-select-available summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: rgba(148, 163, 184, 0.9);
  font-size: 11px;
  line-height: 1.2;
}

.multi-select-status span:last-child,
.multi-select-available summary span:last-child {
  color: rgba(203, 213, 225, 0.78);
}

.multi-select-group-heading {
  color: #e2e8f0;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.multi-select-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 220px;
  overflow: auto;
  padding-right: 2px;
}

.available-list {
  margin-top: 8px;
  max-height: 260px;
}

.multi-select-available {
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  padding-top: 8px;
}

.multi-select-available summary {
  cursor: pointer;
  list-style: none;
}

.multi-select-available summary::-webkit-details-marker {
  display: none;
}

.multi-select-available summary::after {
  content: 'Show';
  color: #7dd3fc;
  font-size: 11px;
}

.multi-select-available[open] summary::after {
  content: 'Hide';
}

.multi-select-empty {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.78);
  border: 1px dashed rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  padding: 10px;
}

.multi-select-empty.compact {
  padding: 8px;
}
</style>
