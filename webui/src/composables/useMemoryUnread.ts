import { onBeforeUnmount, watch, type Ref } from 'vue'
import { useGlobalState } from './useGlobalState'
import { useNodeUnread } from './useNodeUnread'

/** Reading requires successful history delivery and an actually visible conversation. */
export function useMemoryUnread(visible: Ref<boolean>) {
  const { memoryReadReceipt, memoryMode, selectedNodeId, currentGraphId } = useGlobalState()
  const unread = useNodeUnread()
  function acknowledge() {
    const read = memoryReadReceipt.value
    if (!visible.value || document.visibilityState !== 'visible' || !document.hasFocus()) return
    if (!read || memoryMode.value !== 'agent' || read.nodeId !== selectedNodeId.value || read.graphId !== currentGraphId.value) return
    unread.acknowledge(read.graphId, read.nodeId, read.receipt)
  }
  watch([memoryReadReceipt, visible], acknowledge, { flush: 'post' })
  window.addEventListener('focus', acknowledge)
  document.addEventListener('visibilitychange', acknowledge)
  onBeforeUnmount(() => {
    window.removeEventListener('focus', acknowledge)
    document.removeEventListener('visibilitychange', acknowledge)
  })
}
