import { onMounted, onUnmounted, watch, type Ref } from 'vue'

export function useBoardReconnect(options: {
  ready: Ref<boolean>
  canReconnect: () => boolean
  reconnect: () => Promise<void>
  onError: (cause: unknown) => void
}) {
  let inFlight = false
  let disposed = false

  async function resume() {
    if (disposed || inFlight || document.visibilityState !== 'visible'
      || options.ready.value || !options.canReconnect()) return
    inFlight = true
    try { await options.reconnect() }
    catch (cause) { if (!disposed) options.onError(cause) }
    finally { inFlight = false }
  }

  // One attempt per disconnect/foreground/network-restored event. A failed
  // attempt stays visible and leaves manual retry available.
  const stopWatching = watch(options.ready, (ready, previous) => {
    if (previous && !ready) void resume()
  })
  const onResume = () => { void resume() }
  onMounted(() => {
    document.addEventListener('visibilitychange', onResume)
    window.addEventListener('online', onResume)
    window.addEventListener('pageshow', onResume)
  })
  onUnmounted(() => {
    disposed = true
    stopWatching()
    document.removeEventListener('visibilitychange', onResume)
    window.removeEventListener('online', onResume)
    window.removeEventListener('pageshow', onResume)
  })
}
