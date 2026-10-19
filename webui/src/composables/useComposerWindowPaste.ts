import { onBeforeUnmount, onMounted, type Ref } from 'vue'

/** A standalone conversation owns unfocused paste, but never submits the draft. */
export function useComposerWindowPaste(options: {
  active: () => boolean
  text: Ref<string>
  paste: (event: ClipboardEvent) => void | Promise<void>
}) {
  function onPaste(event: ClipboardEvent) {
    if (!options.active() || event.defaultPrevented) return
    const target = event.target instanceof Element ? event.target : null
    // Focused editors handle their own paste, including the chat textarea.
    if (target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) return
    if (document.querySelector('[role="dialog"][aria-modal="true"]')) return
    // The shared attachment handler synchronously claims files/board markers,
    // before uploading asynchronously. Do not also insert their accompanying text.
    void options.paste(event)
    if (event.defaultPrevented) return
    const text = event.clipboardData?.getData('text/plain') || ''
    if (!text) return
    event.preventDefault()
    options.text.value += text
  }
  onMounted(() => window.addEventListener('paste', onPaste))
  onBeforeUnmount(() => window.removeEventListener('paste', onPaste))
}
