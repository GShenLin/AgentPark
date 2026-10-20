function copyTextWithSelectionFallback(text: string) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'true')
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.width = '1px'
  textarea.style.height = '1px'
  textarea.style.opacity = '0'
  textarea.style.pointerEvents = 'none'
  document.body.appendChild(textarea)

  const selection = document.getSelection()
  const previousRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null
  textarea.focus({ preventScroll: true })
  textarea.select()
  textarea.setSelectionRange(0, textarea.value.length)

  try {
    const copied = document.execCommand('copy')
    if (!copied) throw new Error('Copy command was rejected.')
  } finally {
    document.body.removeChild(textarea)
    if (selection) {
      selection.removeAllRanges()
      if (previousRange) selection.addRange(previousRange)
    }
  }
}

export async function copyText(text: string): Promise<void> {
  if (window.agentParkNodeWindow) {
    await window.agentParkNodeWindow.copyText(text)
    return
  }
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
  } else {
    copyTextWithSelectionFallback(text)
  }
}

