<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { UserInteractionField, UserInteractionRequest } from '../api'
import { uploadFiles, type UploadedFileItem } from '../uploadApi'
import ActionButton from './ActionButton.vue'
import ExpandableTextarea from './ExpandableTextarea.vue'
import { t } from '../i18n'
import FormCheckbox from './FormCheckbox.vue'
import FormSelect from './FormSelect.vue'
import FormTextInput from './FormTextInput.vue'

const props = defineProps<{
  request: UserInteractionRequest
  submitting?: boolean
  error?: string
}>()

const emit = defineEmits<{
  submit: [response: Record<string, unknown>]
  error: [message: string]
}>()

const values = reactive<Record<string, unknown>>({})
const selectedFiles = reactive<Record<string, File[]>>({})
const uploaded = reactive<Record<string, UploadedFileItem[]>>({})
const fields = computed(() => props.request.schema?.fields || [])
const graphLabel = computed(() => String(props.request.agent?.graph_id || '').trim())
const nodeLabel = computed(() => String(props.request.agent?.node_name || props.request.agent?.node_id || '').trim())

function fieldKey(field: UserInteractionField) {
  return String(field.id || '').trim()
}

function defaultValue(field: UserInteractionField) {
  if (field.default !== undefined) return field.default
  if (field.type === 'checkbox') return false
  if (field.type === 'multiselect') return []
  return ''
}

function resetForm() {
  for (const key of Object.keys(values)) delete values[key]
  for (const key of Object.keys(selectedFiles)) delete selectedFiles[key]
  for (const key of Object.keys(uploaded)) delete uploaded[key]
  for (const field of fields.value) {
    const key = fieldKey(field)
    if (!key) continue
    values[key] = defaultValue(field)
    selectedFiles[key] = []
    uploaded[key] = []
  }
}

function stringValue(field: UserInteractionField) {
  const value = values[fieldKey(field)]
  return typeof value === 'string' || typeof value === 'number' ? value : ''
}

function setTextValue(field: UserInteractionField, value: string) {
  values[fieldKey(field)] = value
}

function setFiles(field: UserInteractionField, event: Event) {
  selectedFiles[fieldKey(field)] = Array.from((event.target as HTMLInputElement).files || [])
}

function toggleMulti(field: UserInteractionField, optionValue: string) {
  const key = fieldKey(field)
  const current = Array.isArray(values[key]) ? [...(values[key] as string[])] : []
  const index = current.indexOf(optionValue)
  if (index >= 0) current.splice(index, 1)
  else current.push(optionValue)
  values[key] = current
}

function isMultiSelected(field: UserInteractionField, optionValue: string) {
  const current = values[fieldKey(field)]
  return Array.isArray(current) && current.includes(optionValue)
}

async function buildResponse() {
  const filesPayload: Record<string, UploadedFileItem[]> = {}
  const valuesPayload: Record<string, unknown> = { ...values }
  for (const field of fields.value) {
    if (field.type !== 'file') continue
    const key = fieldKey(field)
    const result = await uploadFiles(selectedFiles[key] || [], `interaction-${props.request.id}-${key}`)
    uploaded[key] = result.files
    filesPayload[key] = result.files
  }
  return {
    values: valuesPayload,
    files: filesPayload,
    submitted_at: new Date().toISOString(),
  }
}

async function submitForm() {
  if (props.submitting) return
  try {
    emit('submit', await buildResponse())
  } catch (error) {
    emit('error', error instanceof Error ? error.message : String(error))
  }
}

watch(() => props.request.id, resetForm, { immediate: true })
</script>

<template>
  <p v-if="request.schema.description" class="interaction-description">{{ request.schema.description }}</p>
  <div v-if="graphLabel || nodeLabel" class="interaction-agent">
    <span v-if="graphLabel">Graph：{{ graphLabel }}</span>
    <span v-if="nodeLabel">节点：{{ nodeLabel }}</span>
  </div>

  <div class="interaction-fields">
    <label v-for="field in fields" :key="field.id" class="interaction-field">
      <span class="interaction-label">{{ field.label }}<b v-if="field.required">*</b></span>
      <small v-if="field.description">{{ field.description }}</small>
      <FormTextInput v-if="field.type === 'text'" :model-value="stringValue(field)" :placeholder="field.placeholder || ''" :required="field.required" @update:model-value="setTextValue(field, $event)" />
      <ExpandableTextarea v-else-if="field.type === 'textarea'" :model-value="String(stringValue(field))" :placeholder="field.placeholder || ''" :aria-label="field.label" :required="field.required" @update:model-value="setTextValue(field, $event)" />
      <FormSelect v-else-if="field.type === 'select'" :model-value="stringValue(field)" :required="field.required" @change="setTextValue(field, $event)">
        <option value="" disabled>{{ t('common.choose') }}</option>
        <option v-for="option in field.options || []" :key="option.value" :value="option.value" :disabled="option.disabled">{{ option.label || option.value }}</option>
      </FormSelect>
      <div v-else-if="field.type === 'multiselect'" class="interaction-options">
        <button v-for="option in field.options || []" :key="option.value" type="button" :disabled="option.disabled" :class="{ selected: isMultiSelected(field, option.value) }" @click="toggleMulti(field, option.value)">{{ option.label || option.value }}</button>
      </div>
      <FormCheckbox v-else-if="field.type === 'checkbox'" :model-value="Boolean(values[field.id])" @update:model-value="values[field.id] = $event" />
      <input v-else-if="field.type === 'file'" type="file" :accept="field.accept || undefined" :multiple="field.multiple" :required="field.required" @change="setFiles(field, $event)" />
    </label>
  </div>

  <div v-if="error" class="interaction-error">{{ error }}</div>
  <footer class="interaction-actions">
    <ActionButton variant="primary" :disabled="submitting" @click="submitForm">{{ submitting ? '提交中…' : request.schema.confirm_label || '确认' }}</ActionButton>
  </footer>
</template>
