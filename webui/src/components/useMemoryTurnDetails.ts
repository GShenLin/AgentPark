import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import type { LoadMemoryTurnDetails, MessageEnvelope } from '../api'
import { useMemoryTurnEntries, type FeedTurnEntry } from './memoryFeedTools'

/** Detail requests belong to a turn revision, never to whichever turn is newest. */
export function useMemoryTurnDetails(
  entry: Ref<FeedTurnEntry>,
  loader: () => LoadMemoryTurnDetails,
) {
  const records = ref<MessageEnvelope[]>([])
  const loaded = ref(false)
  const loading = ref(false)
  const error = ref('')
  const requested = ref(false)
  const summary = computed(() => entry.value.userMessage.turn_summary)
  const detailEntries = useMemoryTurnEntries(records)
  const displayEntry = computed(() => {
    const detail = detailEntries.value[0]
    return loaded.value && detail?.type === 'turn' ? detail : entry.value
  })
  let generation = 0
  let pending: Promise<void> | null = null
  let disposed = false

  async function load() {
    requested.value = true
    if (loaded.value) return
    if (pending) return pending
    const turnId = summary.value?.turn_id || entry.value.userMessage.id
    if (!turnId) throw new Error('A turn ID is required to load process details')
    const currentGeneration = generation
    loading.value = true
    error.value = ''
    const request = (async () => {
      try {
        const messages = await loader()(turnId)
        if (disposed || currentGeneration !== generation) return
        if (messages[0]?.id !== turnId) throw new Error('Process response does not match the requested turn')
        records.value = messages
        loaded.value = true
      } catch (cause) {
        if (!disposed && currentGeneration === generation) {
          error.value = cause instanceof Error ? cause.message : String(cause)
        }
        throw cause
      } finally {
        if (currentGeneration === generation) {
          loading.value = false
          pending = null
        }
      }
    })()
    pending = request
    return request
  }

  // Event handlers display failures locally and leave the disclosure retryable.
  function request() { void load().catch(() => { /* error is rendered by the turn */ }) }

  watch(() => summary.value?.revision, () => {
    generation += 1
    pending = null
    records.value = []
    loaded.value = false
    loading.value = false
    error.value = ''
    if (requested.value) request()
  })
  onBeforeUnmount(() => { disposed = true; generation += 1 })
  return { displayEntry, summary, loaded, loading, error, load, request }
}
