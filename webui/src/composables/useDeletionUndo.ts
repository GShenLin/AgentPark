import { ref } from 'vue'
import { undoDeletion } from '../api'

export type DeletionUndoEntry = {
  token: string
  kind: 'delete_node' | 'delete_graph' | 'delete_dialogue'
  label: string
}

const entries = ref<DeletionUndoEntry[]>([])
const undoing = ref(false)

export function recordDeletionUndo(entry: DeletionUndoEntry | null | undefined) {
  if (!entry?.token) return
  entries.value.push(entry)
}

export function useDeletionUndo() {
  async function undoLastDeletion() {
    if (undoing.value) return null
    const entry = entries.value[entries.value.length - 1]
    if (!entry) return null
    undoing.value = true
    try {
      const result = await undoDeletion(entry.token)
      entries.value.pop()
      return { entry, result }
    } finally {
      undoing.value = false
    }
  }

  return {
    entries,
    undoing,
    undoLastDeletion,
  }
}
