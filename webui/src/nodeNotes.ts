export type NodeNotes = Record<string, string>

export function normalizeNodeNotes(value: unknown): NodeNotes {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  const normalized: NodeNotes = {}
  for (const [rawNodeId, rawNote] of Object.entries(value)) {
    const nodeId = String(rawNodeId || '').trim()
    if (!nodeId || typeof rawNote !== 'string') continue
    const note = rawNote.trim()
    if (note) normalized[nodeId] = note
  }
  return normalized
}

export function setNodeNote(notes: NodeNotes, nodeId: string, value: string): NodeNotes {
  const id = String(nodeId || '').trim()
  if (!id) return notes
  const next = { ...notes }
  const note = String(value || '').trim()
  if (note) next[id] = note
  else delete next[id]
  return next
}

export function renameNodeNote(notes: NodeNotes, oldNodeId: string, newNodeId: string): NodeNotes {
  const oldId = String(oldNodeId || '').trim()
  const newId = String(newNodeId || '').trim()
  if (!oldId || !newId || oldId === newId || !(oldId in notes)) return notes
  const next = { ...notes, [newId]: notes[oldId]! }
  delete next[oldId]
  return next
}

export function removeNodeNote(notes: NodeNotes, nodeId: string): NodeNotes {
  const id = String(nodeId || '').trim()
  if (!id || !(id in notes)) return notes
  const next = { ...notes }
  delete next[id]
  return next
}
