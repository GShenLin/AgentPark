import { computed, ref } from 'vue'
import { getActiveApiBase } from '../api'
import type { UserInteractionRequest } from '../apiTypes'
import { listUserInteractions, submitUserInteraction } from '../userInteractionApi'
import { clearInteractionDraft } from '../interactionFormState'
import { useGlobalState } from './useGlobalState'

const requests = ref<UserInteractionRequest[]>([])
const activeIndex = ref(0)
const loading = ref(false)
const submittingRequestId = ref('')
const loadError = ref('')
let refreshPromise: Promise<void> | null = null
let refreshQueued = false
const completedIds = new Set<string>()

const activeRequest = computed(() => requests.value[activeIndex.value] || null)

function replaceRequests(nextRequests: UserInteractionRequest[]) {
  nextRequests = nextRequests.filter(item => !completedIds.has(item.id))
  const activeId = activeRequest.value?.id || ''
  requests.value = nextRequests
  if (!nextRequests.length) {
    activeIndex.value = 0
    return
  }
  const preservedIndex = activeId ? nextRequests.findIndex((item) => item.id === activeId) : -1
  activeIndex.value = preservedIndex >= 0 ? preservedIndex : Math.min(activeIndex.value, nextRequests.length - 1)
}

export function primeUserInteractions(nextRequests: UserInteractionRequest[]) {
  replaceRequests(nextRequests)
}

async function runRefresh() {
  loading.value = true
  loadError.value = ''
  try {
    replaceRequests(await listUserInteractions())
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error)
    throw error
  } finally {
    loading.value = false
  }
}

async function refreshRequests() {
  if (refreshPromise) {
    refreshQueued = true
    return refreshPromise
  }
  refreshPromise = (async () => {
    do {
      refreshQueued = false
      await runRefresh()
    } while (refreshQueued)
  })()
  try {
    await refreshPromise
  } finally {
    refreshPromise = null
  }
}

function setActiveIndex(index: number) {
  if (!requests.value.length) {
    activeIndex.value = 0
    return
  }
  activeIndex.value = Math.max(0, Math.min(index, requests.value.length - 1))
}

function showPrevious() {
  if (requests.value.length < 2) return
  activeIndex.value = (activeIndex.value - 1 + requests.value.length) % requests.value.length
}

function showNext() {
  if (requests.value.length < 2) return
  activeIndex.value = (activeIndex.value + 1) % requests.value.length
}

async function submitResponse(requestId: string, response: Record<string, unknown>, status: 'submitted' | 'cancelled' = 'submitted') {
  const safeRequestId = String(requestId || '').trim()
  if (!safeRequestId || submittingRequestId.value) return
  submittingRequestId.value = safeRequestId
  try {
    await submitUserInteraction(safeRequestId, response, status)
    completedIds.add(safeRequestId)
    replaceRequests(requests.value.filter((item) => item.id !== safeRequestId))
    clearInteractionDraft(safeRequestId, getActiveApiBase(), localStorage)
    useGlobalState().memoryRefreshRequest.value += 1
  } finally {
    submittingRequestId.value = ''
  }
}

function notifyUserInteractionGraphEvent(payload: Record<string, unknown>) {
  const eventName = String(payload.event || '').trim()
  const source = String(payload.source || '').trim()
  const stage = String(payload.stage || '').trim()
  const isInteractionEvent =
    eventName === 'stream_gap' || eventName === 'stream_snapshot' || eventName === 'user_interaction_delivery' ||
    eventName === 'user_interaction_submitted' ||
    eventName === 'user_interaction_cancelled' ||
    eventName === 'user_interaction_expired' ||
    (eventName === 'runtime_notice' && source === 'user_interaction' && stage.startsWith('user_interaction_'))
  if (!isInteractionEvent) return
  void refreshRequests().catch(() => undefined)
}

export function useUserInteractions() {
  return {
    requests,
    activeIndex,
    activeRequest,
    loading,
    submittingRequestId,
    loadError,
    refreshRequests,
    setActiveIndex,
    showPrevious,
    showNext,
    submitResponse,
  }
}

export { notifyUserInteractionGraphEvent }
