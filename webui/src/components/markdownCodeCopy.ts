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

async function copyText(text: string) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
  } else {
    copyTextWithSelectionFallback(text)
  }
}

function showCopiedState(button: HTMLButtonElement) {
  const previousText = button.textContent || 'Copy'
  const previousTitle = button.getAttribute('title') || 'Copy code'
  button.textContent = 'Copied'
  button.setAttribute('title', 'Copied')
  button.classList.add('copied')
  window.setTimeout(() => {
    button.textContent = previousText
    button.setAttribute('title', previousTitle)
    button.classList.remove('copied')
  }, 1400)
}

export async function handleMarkdownCodeCopyClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  const button = target?.closest('.markdown-code-copy') as HTMLButtonElement | null
  if (!button) return

  event.preventDefault()
  event.stopPropagation()

  const block = button.closest('.markdown-code-block')
  const code = block?.querySelector('pre code')?.textContent || ''
  if (!code) return

  try {
    await copyText(code)
    showCopiedState(button)
  } catch {
    button.textContent = 'Failed'
    button.setAttribute('title', 'Copy failed')
    window.setTimeout(() => {
      button.textContent = 'Copy'
      button.setAttribute('title', 'Copy code')
    }, 1400)
  }
}
