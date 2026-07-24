<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { UserInteractionRequest } from '../api'
import { useUserInteractions } from '../composables/useUserInteractions'
import UserInteractionForm from './UserInteractionForm.vue'

type InteractionNodeAnchor = {
  id: string
  ui: { x: number; y: number }
}

const props = withDefaults(defineProps<{
  nodes?: InteractionNodeAnchor[]
  canvasWidth?: number
  canvasHeight?: number
  global?: boolean
}>(), {
  nodes: () => [],
  canvasWidth: 0,
  canvasHeight: 0,
  global: false,
})

const NODE_WIDTH = 200
const DIALOG_WIDTH = 420
const DIALOG_MARGIN = 16
const interactions = useUserInteractions()
const positions = ref<Record<string, { x: number; y: number }>>({})
const error = ref('')
const dragSession = ref<{
  requestId: string
  startPointerX: number
  startPointerY: number
  startX: number
  startY: number
} | null>(null)

const activeRequest = interactions.activeRequest
const activeRequestId = computed(() => activeRequest.value?.id || '')
const anchorNode = computed(() => {
  const nodeId = String(activeRequest.value?.agent?.node_id || '').trim()
  return nodeId ? props.nodes.find((node) => String(node.id || '').trim() === nodeId) || null : null
})
const activePosition = computed(() => {
  const request = activeRequest.value
  if (!request) return { x: DIALOG_MARGIN, y: DIALOG_MARGIN }
  return positions.value[request.id] || defaultPosition(request)
})
const dialogStyle = computed(() => ({
  left: `${activePosition.value.x}px`,
  top: `${activePosition.value.y}px`,
  width: `${DIALOG_WIDTH}px`,
}))
const submitting = computed(() => interactions.submittingRequestId.value === activeRequestId.value)

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
  return node?.ui
    ? clampPosition({ x: node.ui.x + NODE_WIDTH + DIALOG_MARGIN, y: node.ui.y })
    : clampPosition({ x: DIALOG_MARGIN, y: DIALOG_MARGIN })
}

function ensureRequestPosition(request: UserInteractionRequest | null) {
  if (!request || positions.value[request.id]) return
  positions.value[request.id] = defaultPosition(request)
}

function onDragMove(event: PointerEvent) {
  const session = dragSession.value
  if (!session) return
  positions.value[session.requestId] = clampPosition({
    x: session.startX + event.clientX - session.startPointerX,
    y: session.startY + event.clientY - session.startPointerY,
  })
  event.preventDefault()
}

function endDrag(event?: PointerEvent) {
  if (!dragSession.value) return
  dragSession.value = null
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', endDrag)
  window.removeEventListener('pointercancel', endDrag)
  if (event?.cancelable) event.preventDefault()
}

function startDrag(event: PointerEvent) {
  const request = activeRequest.value
  if (!request || event.button !== 0) return
  dragSession.value = {
    requestId: request.id,
    startPointerX: event.clientX,
    startPointerY: event.clientY,
    startX: activePosition.value.x,
    startY: activePosition.value.y,
  }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', endDrag)
  window.addEventListener('pointercancel', endDrag)
  event.preventDefault()
}

async function submitActive(response: Record<string, unknown>) {
  const request = activeRequest.value
  if (!request) return
  error.value = ''
  try {
    await interactions.submitResponse(request.id, response)
  } catch (submitError) {
    error.value = submitError instanceof Error ? submitError.message : String(submitError)
  }
}

watch(activeRequestId, () => { error.value = '' })
watch(activeRequest, ensureRequestPosition, { immediate: true })
watch(() => [props.canvasWidth, props.canvasHeight, activeRequestId.value] as const, () => {
  const requestId = activeRequestId.value
  if (requestId && positions.value[requestId]) positions.value[requestId] = clampPosition(positions.value[requestId])
})

onBeforeUnmount(() => {
  endDrag()
})
</script>

<template>
  <div v-if="activeRequest" class="interaction-layer" :class="{ 'interaction-layer-global': props.global }">
    <section class="interaction-dialog" :class="{ dragging: dragSession }" :style="dialogStyle" role="dialog" aria-modal="false" @pointerdown.stop @click.stop @mousedown.stop @wheel.stop>
      <header class="interaction-header">
        <div>
          <div class="interaction-kicker">Agent 请求输入<span v-if="anchorNode"> · 贴近节点</span></div>
          <h2>{{ activeRequest.schema.title }}</h2>
        </div>
        <button type="button" class="interaction-drag-handle" title="拖动交互框" @pointerdown.stop="startDrag">拖动</button>
      </header>
      <div v-if="interactions.requests.value.length > 1" class="interaction-navigation">
        <button type="button" @click="interactions.showPrevious">上一项</button>
        <span class="interaction-count">{{ interactions.activeIndex.value + 1 }} / {{ interactions.requests.value.length }}</span>
        <button type="button" @click="interactions.showNext">下一项</button>
      </div>
      <UserInteractionForm :request="activeRequest" :submitting="submitting" :error="error" @submit="submitActive" @error="error = $event" />
    </section>
  </div>
</template>
