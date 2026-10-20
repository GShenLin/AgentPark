import { copyText } from '../clipboard'

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
