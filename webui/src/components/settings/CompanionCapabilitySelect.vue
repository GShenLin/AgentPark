<script setup lang="ts">
import { computed, ref } from 'vue'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import FieldMultiSelect from '../agent-board/FieldMultiSelect.vue'

export type CompanionCapabilityOption = {
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

const props = defineProps<{
  title: string
  values: string[]
  options: CompanionCapabilityOption[]
  emptyText: string
  addPlaceholder: string
}>()

const emit = defineEmits<{
  'update:values': [value: string[]]
}>()

const newValue = ref('')

const normalizedValues = computed(() => normalizeStrings(props.values))
const normalizedOptions = computed(() => {
  const known = normalizeOptions(props.options)
  const selected = normalizedValues.value
  const seen = new Set(known.map((item) => item.value))
  const selectedOptions = selected
    .filter((value) => !seen.has(value))
    .map((value) => ({ value, label: value, status: 'unavailable', diagnostics: [`selected capability is not available: ${value}`] }))
  return [...selectedOptions, ...known]
})

function normalizeStrings(values: unknown[]) {
  const seen = new Set<string>()
  const result: string[] = []
  for (const item of values || []) {
    const value = String(item || '').trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    result.push(value)
  }
  return result
}

function normalizeOptions(options: CompanionCapabilityOption[]) {
  const seen = new Set<string>()
  const result: CompanionCapabilityOption[] = []
  for (const option of options || []) {
    const value = String(option?.value || '').trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    result.push({
      ...option,
      value,
      label: String(option.label || value).trim() || value,
    })
  }
  return result
}

function updateValues(values: string[]) {
  emit('update:values', normalizeStrings(values))
}

function toggleValue(value: string) {
  const optionValue = String(value || '').trim()
  if (!optionValue) return
  const current = normalizedValues.value
  updateValues(current.includes(optionValue)
    ? current.filter((item) => item !== optionValue)
    : [...current, optionValue])
}

function addCustomValue() {
  const value = newValue.value.trim()
  if (!value) return
  updateValues([...normalizedValues.value, value])
  newValue.value = ''
}
</script>

<template>
  <section class="capability-select">
    <div class="capability-head">
      <h3>{{ title }}</h3>
      <div class="capability-add">
        <FormTextInput v-model="newValue" :placeholder="addPlaceholder" @keydown.enter.prevent="addCustomValue" />
        <ActionButton compact @click="addCustomValue">Add</ActionButton>
      </div>
    </div>
    <FieldMultiSelect
      :label="title"
      :options="normalizedOptions"
      :selected-values="normalizedValues"
      :empty-text="emptyText"
      @toggle="toggleValue"
    />
  </section>
</template>

<style scoped>
.capability-select {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.capability-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.capability-head h3 {
  margin: 0;
  font-size: 13px;
}

.capability-add {
  display: flex;
  min-width: min(260px, 52%);
  gap: 6px;
}

.capability-add .form-text-input {
  min-width: 0;
  flex: 1;
}

@media (max-width: 760px) {
  .capability-head {
    align-items: stretch;
    flex-direction: column;
  }

  .capability-add {
    min-width: 0;
    width: 100%;
  }
}
</style>
