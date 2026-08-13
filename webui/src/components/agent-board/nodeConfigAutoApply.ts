export type NodeConfigAutoApplyBatch = {
  nodeId: string
  fields: Record<string, unknown>
}

type NodeConfigAutoApplyOptions = {
  persist: (batch: NodeConfigAutoApplyBatch) => Promise<void>
  onError: (error: unknown, batch: NodeConfigAutoApplyBatch) => void
  onBusyChange?: (busy: boolean) => void
}

export function createNodeConfigAutoApplyQueue(options: NodeConfigAutoApplyOptions) {
  const pendingByNode = new Map<string, Record<string, unknown>>()
  let draining: Promise<void> | null = null

  async function drain() {
    options.onBusyChange?.(true)
    try {
      while (pendingByNode.size > 0) {
        const entry = pendingByNode.entries().next().value as [string, Record<string, unknown>] | undefined
        if (!entry) break
        const [nodeId, fields] = entry
        pendingByNode.delete(nodeId)
        const batch = { nodeId, fields: { ...fields } }
        try {
          await options.persist(batch)
        } catch (error) {
          options.onError(error, batch)
        }
      }
    } finally {
      draining = null
      options.onBusyChange?.(false)
    }
  }

  function enqueue(nodeId: string, key: string, value: unknown) {
    const safeNodeId = String(nodeId || '').trim()
    const safeKey = String(key || '').trim()
    if (!safeNodeId || !safeKey) return Promise.resolve()
    const current = pendingByNode.get(safeNodeId) || {}
    pendingByNode.set(safeNodeId, { ...current, [safeKey]: value })
    options.onBusyChange?.(true)
    if (!draining) draining = Promise.resolve().then(drain)
    return draining
  }

  function flush() {
    return draining || Promise.resolve()
  }

  return { enqueue, flush }
}
