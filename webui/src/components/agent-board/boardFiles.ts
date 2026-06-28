export type BoardAttachment = {
  path: string
  name: string
}

export function isBoardFileDropEvent(event: DragEvent) {
  const types = Array.from(event.dataTransfer?.types || [])
  return types.includes('application/x-aitools-file') || types.includes('Files')
}

export function appendUniqueBoardAttachment(
  attachments: BoardAttachment[],
  path: string,
  name = '',
) {
  const safePath = String(path || '').trim()
  const safeName = String(name || '').trim() || safePath
  if (!safePath) return false
  if (attachments.some((item) => item.path === safePath)) return false
  attachments.push({ path: safePath, name: safeName })
  return true
}
