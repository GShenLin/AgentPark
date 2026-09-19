/** Cloud Board exports to the browsing device, without server filesystem access. */
export function downloadMarkdown(text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `memory-${new Date().toISOString().replace(/[:.]/g, '-')}.md`
  document.body.appendChild(link)
  try {
    link.click()
  } finally {
    link.remove()
    // Keep the object URL alive until the browser has started its download.
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
}
