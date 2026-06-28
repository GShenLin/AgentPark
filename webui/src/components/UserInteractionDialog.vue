<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { listUserInteractions, submitUserInteraction, type UserInteractionField, type UserInteractionRequest } from '../api'
import { uploadFiles, type UploadedFileItem } from '../uploadApi'
import { useGlobalState } from '../composables/useGlobalState'
import UserInteractionCustomFrame from './UserInteractionCustomFrame.vue'

type InteractionNodeAnchor = {
  id: string
  ui: { x: number; y: number }
}

const props = withDefaults(
  defineProps<{
    nodes?: InteractionNodeAnchor[]
    canvasWidth?: number
    canvasHeight?: number
  }>(),
  {
    nodes: () => [],
    canvasWidth: 0,
    canvasHeight: 0,
  },
)

const NODE_WIDTH = 200
const DIALOG_WIDTH = 420
const DIALOG_MARGIN = 16

const { memoryRefreshRequest } = useGlobalState()

const requests = ref<UserInteractionRequest[]>([])
const activeIndex = ref(0)
const values = reactive<Record<string, unknown>>({})
const selectedFiles = reactive<Record<string, File[]>>({})
const uploaded = reactive<Record<string, UploadedFileItem[]>>({})
const customValues = reactive<Record<string, Record<string, unknown>>>({})
const positions = reactive<Record<string, { x: number; y: number }>>({})
const submitting = ref(false)
const error = ref('')
const dragSession = ref<{
  requestId: string
  pointerId: number
  startPointerX: number
  startPointerY: number
  startX: number
  startY: number
} | null>(null)

const activeRequest = computed(() => requests.value[activeIndex.value] || null)
const activeRequestId = computed(() => activeRequest.value?.id || '')
const fields = computed(() => activeRequest.value?.schema?.fields || [])
const anchorNode = computed(() => {
  const nodeId = String(activeRequest.value?.agent?.node_id || '').trim()
  if (!nodeId) return null
  return props.nodes.find((node) => String(node.id || '').trim() === nodeId) || null
})
const activePosition = computed(() => {
  const request = activeRequest.value
  if (!request) return { x: DIALOG_MARGIN, y: DIALOG_MARGIN }
  return positions[request.id] || defaultPosition(request)
})
const dialogStyle = computed(() => ({
  left: `${activePosition.value.x}px`,
  top: `${activePosition.value.y}px`,
  width: `${DIALOG_WIDTH}px`,
}))

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

function stringValue(field: UserInteractionField) {
  const value = values[fieldKey(field)]
  return typeof value === 'string' || typeof value === 'number' ? value : ''
}

function setTextValue(field: UserInteractionField, event: Event) {
  values[fieldKey(field)] = (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null)?.value || ''
}

function resetForm(request: UserInteractionRequest | null) {
  error.value = ''
  for (const key of Object.keys(values)) delete values[key]
  for (const key of Object.keys(selectedFiles)) delete selectedFiles[key]
  for (const key of Object.keys(uploaded)) delete uploaded[key]
  for (const key of Object.keys(customValues)) delete customValues[key]
  for (const field of request?.schema?.fields || []) {
    const key = fieldKey(field)
    if (!key) continue
    values[key] = defaultValue(field)
    selectedFiles[key] = []
    uploaded[key] = []
    customValues[key] = {}
  }
}

function clampPosition(position: { x: number; y: number }) {
  const maxX = Math.max(DIALOG_MARGIN, Number(props.canvasWidth || 0) - DIALOG_WIDTH - DIALOG_MARGIN)
  const maxY = Math.max(DIALOG_MARGIN, Number(props.canvasHeight || 0) - 240)
  return {
    x: Math.min(Math.max(DIALOG_MARGIN, position.x), maxX),
    y: Math.min(Math.max(DIALOG_MARGIN, position.y), maxY),
  }
}

function defaultPosition(request: UserInteractionRequest) {
  const nodeId = String(request.agent?.node_id || '').trim()
  const node = nodeId ? props.nodes.find((item) => String(item.id || '').trim() === nodeId) : null
  if (node?.ui) {
    return clampPosition({
      x: node.ui.x + NODE_WIDTH + DIALOG_MARGIN,
      y: node.ui.y,
    })
  }
  return clampPosition({ x: DIALOG_MARGIN, y: DIALOG_MARGIN })
}

function ensureRequestPosition(request: UserInteractionRequest | null) {
  if (!request || positions[request.id]) return
  positions[request.id] = defaultPosition(request)
}

function onDragMove(event: PointerEvent) {
  const session = dragSession.value
  if (!session) return
  positions[session.requestId] = clampPosition({
    x: session.startX + event.clientX - session.startPointerX,
    y: session.startY + event.clientY - session.startPointerY,
  })
  event.preventDefault()
}

function endDrag(event?: PointerEvent) {
  const session = dragSession.value
  if (!session) return
  dragSession.value = null
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', endDrag)
  window.removeEventListener('pointercancel', endDrag)
  if (event?.cancelable) event.preventDefault()
}

function startDrag(event: PointerEvent) {
  const request = activeRequest.value
  if (!request || event.button !== 0) return
  const position = activePosition.value
  dragSession.value = {
    requestId: request.id,
    pointerId: event.pointerId,
    startPointerX: event.clientX,
    startPointerY: event.clientY,
    startX: position.x,
    startY: position.y,
  }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', endDrag)
  window.addEventListener('pointercancel', endDrag)
  event.preventDefault()
}

function setFiles(field: UserInteractionField, event: Event) {
  const key = fieldKey(field)
  const input = event.target as HTMLInputElement
  selectedFiles[key] = Array.from(input.files || [])
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

async function submitCustomValue(field: UserInteractionField, value: Record<string, unknown>) {
  mergeCustomValue(field, value)
  await submitActive()
}

async function refreshRequests() {
  if (submitting.value) return
  try {
    const pending = await listUserInteractions()
    requests.value = pending
    if (activeIndex.value >= pending.length) activeIndex.value = 0
  } catch {
    // The interaction dialog is best-effort while the backend restarts or reconnects.
  }
}

async function submitActive() {
  const request = activeRequest.value
  if (!request || submitting.value) return

  submitting.value = true
  error.value = ''
  try {
    const filesPayload: Record<string, UploadedFileItem[]> = {}
    const valuesPayload: Record<string, unknown> = { ...values }
    for (const [key, value] of Object.entries(customValues)) {
      if (Object.keys(value || {}).length > 0) valuesPayload[key] = value
    }
    for (const field of fields.value) {
      if (field.type === 'custom_html' && valuesPayload[fieldKey(field)] === undefined) delete valuesPayload[fieldKey(field)]
    }
    for (const field of fields.value) {
      if (field.type !== 'file') continue
      const key = fieldKey(field)
      const files = selectedFiles[key] || []
      const result = await uploadFiles(files, `interaction-${request.id}-${key}`)
      uploaded[key] = result.files
      filesPayload[key] = result.files
    }
    await submitUserInteraction(request.id, {
      values: valuesPayload,
      custom_values: { ...customValues },
      files: filesPayload,
      submitted_at: new Date().toISOString(),
    })
    requests.value = requests.value.filter((item) => item.id !== request.id)
    memoryRefreshRequest.value += 1
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    submitting.value = false
  }
}

watch(activeRequestId, () => resetForm(activeRequest.value), { immediate: true })
watch(activeRequest, (request) => ensureRequestPosition(request), { immediate: true })
watch(
  () => [props.canvasWidth, props.canvasHeight, activeRequestId.value] as const,
  () => {
    const requestId = activeRequestId.value
    if (!requestId || !positions[requestId]) return
    positions[requestId] = clampPosition(positions[requestId])
  },
)

onMounted(() => {
  void refreshRequests()
})

onBeforeUnmount(() => {
  endDrag()
})
</script>

<template>
  <div v-if="activeRequest" class="interaction-layer">
    <section
      class="interaction-dialog"
      :class="{ dragging: dragSession }"
      :style="dialogStyle"
      role="dialog"
      aria-modal="false"
      @pointerdown.stop
      @click.stop
      @mousedown.stop
      @wheel.stop
    >
        <header class="interaction-header">
          <div>
            <div class="interaction-kicker">Agent 请求输入<span v-if="anchorNode"> · 贴近节点</span></div>
            <h2>{{ activeRequest.schema.title }}</h2>
          </div>
          <button type="button" class="interaction-drag-handle" title="拖动交互框" @pointerdown.stop="startDrag">拖动</button>
          <div v-if="requests.length > 1" class="interaction-count">{{ activeIndex + 1 }} / {{ requests.length }}</div>
        </header>

        <p v-if="activeRequest.schema.description" class="interaction-description">{{ activeRequest.schema.description }}</p>
        <div v-if="activeRequest.agent?.node_id || activeRequest.agent?.node_name" class="interaction-agent">
          {{ activeRequest.agent?.node_name || activeRequest.agent?.node_id }}
        </div>

        <div class="interaction-fields">
          <label v-for="field in fields" :key="field.id" class="interaction-field">
            <span class="interaction-label">{{ field.label }}<b v-if="field.required">*</b></span>
            <small v-if="field.description">{{ field.description }}</small>

            <input
              v-if="field.type === 'text'"
              type="text"
              :value="stringValue(field)"
              :placeholder="field.placeholder || ''"
              @input="setTextValue(field, $event)"
            />
            <textarea
              v-else-if="field.type === 'textarea'"
              rows="5"
              :value="stringValue(field)"
              :placeholder="field.placeholder || ''"
              @input="setTextValue(field, $event)"
            ></textarea>
            <select v-else-if="field.type === 'select'" :value="stringValue(field)" @change="setTextValue(field, $event)">
              <option value="" disabled>请选择</option>
              <option v-for="option in field.options || []" :key="option.value" :value="option.value" :disabled="option.disabled">
                {{ option.label || option.value }}
              </option>
            </select>
            <div v-else-if="field.type === 'multiselect'" class="interaction-options">
              <button
                v-for="option in field.options || []"
                :key="option.value"
                type="button"
                :disabled="option.disabled"
                :class="{ selected: isMultiSelected(field, option.value) }"
                @click="toggleMulti(field, option.value)"
              >
                {{ option.label || option.value }}
              </button>
            </div>
            <input v-else-if="field.type === 'checkbox'" v-model="values[field.id]" type="checkbox" />
            <input
              v-else-if="field.type === 'file'"
              type="file"
              :accept="field.accept || undefined"
              :multiple="field.multiple"
              @change="setFiles(field, $event)"
            />
            <UserInteractionCustomFrame
              v-else-if="field.type === 'custom_html'"
              :field="field"
              :request-id="activeRequest.id"
              @change="mergeCustomValue(field, $event)"
              @submit="submitCustomValue(field, $event)"
              @error="error = $event"
            />
          </label>
        </div>

        <div v-if="error" class="interaction-error">{{ error }}</div>
        <footer class="interaction-actions">
          <button type="button" :disabled="submitting" @click="submitActive">
            {{ submitting ? '提交中…' : activeRequest.schema.confirm_label || '确认' }}
          </button>
        </footer>
      </section>
  </div>
</template>
