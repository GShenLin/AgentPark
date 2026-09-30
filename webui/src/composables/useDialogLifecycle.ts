import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue'

const dialogs: HTMLElement[] = []
const selector = 'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])'

/** One owner for modal focus, layered Escape handling and keyboard containment. */
export function useDialogLifecycle(element: Ref<HTMLElement | null>, open: Ref<boolean>, close: () => void) {
  let release: (() => void) | undefined
  function isTop(dialog: HTMLElement) {
    if (dialog.closest('[inert]')) return false
    if (dialogs[dialogs.length - 1] !== dialog) return false
    // Existing dialogs that have not adopted this lifecycle still own their
    // dismissal. Never close a conversation behind one of those dialogs.
    return !Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]'))
      .some(other => other !== dialog && other.getClientRects().length && !dialogs.includes(other))
  }
  watch([element, open], async ([dialog, active], _, onCleanup) => {
    if (!dialog || !active) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    dialogs.push(dialog)
    let disposed = false
    function keydown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.isComposing || !isTop(dialog!)) return
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopImmediatePropagation(); close()
      } else if (event.key === 'Tab') {
        const candidates = Array.from(dialog!.querySelectorAll<HTMLElement>(selector)).filter(el => el.getClientRects().length)
        const first = candidates[0], last = candidates[candidates.length - 1]
        if (!first || !last) { event.preventDefault(); dialog!.focus({ preventScroll: true }); return }
        const focus = document.activeElement
        if (!dialog!.contains(focus) || focus === dialog || (event.shiftKey ? focus === first : focus === last)) {
          event.preventDefault(); (event.shiftKey ? last : first).focus({ preventScroll: true })
        }
      }
    }
    window.addEventListener('keydown', keydown)
    const cleanup = () => {
      if (disposed) return
      disposed = true
      const wasTop = dialogs[dialogs.length - 1] === dialog
      const index = dialogs.indexOf(dialog)
      if (index >= 0) dialogs.splice(index, 1)
      window.removeEventListener('keydown', keydown)
      if (wasTop && previous?.isConnected) previous.focus({ preventScroll: true })
    }
    release = cleanup
    onCleanup(cleanup)
    await nextTick()
    if (!disposed && isTop(dialog) && !dialog.contains(document.activeElement)) dialog.focus({ preventScroll: true })
  }, { flush: 'post' })
  onBeforeUnmount(() => release?.())
}
