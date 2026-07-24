<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { UserInteractionField, UserInteractionRequest } from '../api'
import { uploadFiles, type UploadedFileItem } from '../uploadApi'
import UserInteractionCustomFrame from './UserInteractionCustomFrame.vue'

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
const customValues = reactive<Record<string, Record<string, unknown>>>({})
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
  if (field.type === 'custom_html') return undefined
  return ''
}

function resetForm() {
  for (const key of Object.keys(values)) delete values[key]
  for (const key of Object.keys(selectedFiles)) delete selectedFiles[key]
  for (const key of Object.keys(uploaded)) delete uploaded[key]
  for (const key of Object.keys(customValues)) delete customValues[key]
  for (const field of fields.value) {
    const key = fieldKey(field)
    if (!key) continue
    values[key] = defaultValue(field)
    selectedFiles[key] = []
    uploaded[key] = []
    customValues[key] = {}
  }
}

function stringValue(field: UserInteractionField) {
  const value = values[fieldKey(field)]
  return typeof value === 'string' || typeof value === 'number' ? value : ''
}

function setTextValue(field: UserInteractionField, event: Event) {
  values[fieldKey(field)] = (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null)?.value || ''
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

function mergeCustomValue(field: UserInteractionField, value: Record<string, unknown>) {
  const key = fieldKey(field)
  customValues[key] = { ...(customValues[key] || {}), ...value }
}

async function buildResponse() {
  const filesPayload: Record<string, UploadedFileItem[]> = {}
  const valuesPayload: Record<string, unknown> = { ...values }
  for (const [key, value] of Object.entries(customValues)) {
    if (Object.keys(value || {}).length > 0) valuesPayload[key] = value
  }
  for (const field of fields.value) {
    if (field.type === 'custom_html' && valuesPayload[fieldKey(field)] === undefined) delete valuesPayload[fieldKey(field)]
    if (field.type !== 'file') continue
    const key = fieldKey(field)
    const result = await uploadFiles(selectedFiles[key] || [], `interaction-${props.request.id}-${key}`)
    uploaded[key] = result.files
    filesPayload[key] = result.files
  }
  return {
    values: valuesPayload,
    custom_values: { ...customValues },
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

async function submitCustomValue(field: UserInteractionField, value: Record<string, unknown>) {
  mergeCustomValue(field, value)
  await submitForm()
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
      <input v-if="field.type === 'text'" type="text" :value="stringValue(field)" :placeholder="field.placeholder || ''" :required="field.required" @input="setTextValue(field, $event)" />
      <textarea v-else-if="field.type === 'textarea'" rows="5" :value="stringValue(field)" :placeholder="field.placeholder || ''" :required="field.required" @input="setTextValue(field, $event)"></textarea>
      <select v-else-if="field.type === 'select'" :value="stringValue(field)" :required="field.required" @change="setTextValue(field, $event)">
        <option value="" disabled>请选择</option>
        <option v-for="option in field.options || []" :key="option.value" :value="option.value" :disabled="option.disabled">{{ option.label || option.value }}</option>
      </select>
      <div v-else-if="field.type === 'multiselect'" class="interaction-options">
        <button v-for="option in field.options || []" :key="option.value" type="button" :disabled="option.disabled" :class="{ selected: isMultiSelected(field, option.value) }" @click="toggleMulti(field, option.value)">{{ option.label || option.value }}</button>
      </div>
      <input v-else-if="field.type === 'checkbox'" v-model="values[field.id]" type="checkbox" />
      <input v-else-if="field.type === 'file'" type="file" :accept="field.accept || undefined" :multiple="field.multiple" :required="field.required" @change="setFiles(field, $event)" />
      <UserInteractionCustomFrame v-else-if="field.type === 'custom_html'" :field="field" :request-id="request.id" @change="mergeCustomValue(field, $event)" @submit="submitCustomValue(field, $event)" @error="emit('error', $event)" />
    </label>
  </div>

  <div v-if="error" class="interaction-error">{{ error }}</div>
  <footer class="interaction-actions">
    <button type="button" :disabled="submitting" @click="submitForm">{{ submitting ? '提交中…' : request.schema.confirm_label || '确认' }}</button>
  </footer>
</template>
