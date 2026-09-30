import { nextTick, watch, type Ref, type WatchSource } from 'vue'

/** Enter a conversation at its end; preserve the reader's position on updates. */
export function useMobileChatScroll(
  feed: Ref<HTMLElement | null>,
  selection: WatchSource<string>,
  ready: WatchSource<boolean>,
  content: WatchSource[],
) {
  function scrollToBottom() {
    const element = feed.value
    if (element) element.scrollTop = element.scrollHeight
  }

  // The container and the first response may become available in either order.
  watch([feed, selection, ready], ([element, key, loaded]) => {
    if (element && key && loaded) scrollToBottom()
  }, { flush: 'post', immediate: true })

  watch(content, async (_value, _previous, onCleanup) => {
    const element = feed.value
    if (!element || element.scrollHeight - element.scrollTop - element.clientHeight > 48) return
    let cancelled = false
    onCleanup(() => { cancelled = true })
    // Measure before rendering; growing history must not cancel bottom following.
    await nextTick()
    if (!cancelled && feed.value === element) scrollToBottom()
  }, { deep: true, flush: 'pre' })

  return { scrollToBottom }
}
