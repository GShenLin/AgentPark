import { ref } from 'vue'

const PREFIX = 'agentpark.node-unread:'
const unread = ref<Record<string, string>>({})
let initialized = false
const keyFor = (graphId: string, nodeId: string) => `${PREFIX}${JSON.stringify([graphId, nodeId])}`

function initialize() {
  if (initialized || typeof window === 'undefined') return
  initialized = true
  for (let i = 0; i < window.localStorage.length; i++) {
    const key = window.localStorage.key(i)
    if (key?.startsWith(PREFIX)) unread.value[key] = window.localStorage.getItem(key) || ''
  }
  window.addEventListener('storage', event => {
    if (event.key?.startsWith(PREFIX)) unread.value = { ...unread.value, [event.key]: event.newValue || '' }
  })
}

export function recordNodeUnread(graphId: string, nodeId: string, alertId: string) {
  initialize()
  const key = keyFor(graphId, nodeId)
  unread.value = { ...unread.value, [key]: alertId }
  if (typeof window !== 'undefined') window.localStorage.setItem(key, alertId)
}

export function useNodeUnread() {
  initialize()
  return {
    unread,
    receipt: (graphId: string, nodeId: string) => unread.value[keyFor(graphId, nodeId)] || '',
    acknowledge(graphId: string, nodeId: string, receipt: string) {
      const key = keyFor(graphId, nodeId)
      // A newer completion arriving while history loads must remain unread.
      if (unread.value[key] !== receipt) return
      unread.value = { ...unread.value, [key]: '' }
      if (typeof window !== 'undefined') window.localStorage.removeItem(key)
    },
  }
}
