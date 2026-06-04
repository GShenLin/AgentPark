const API_BASE = (import.meta as any).env?.VITE_API_BASE || ''

export type UploadedFileItem = {
  path: string
  name: string
  kind: string
  mime: string
  size: number
  source: string
}

export async function uploadFiles(files: File[], traceId = ''): Promise<{ files: UploadedFileItem[]; trace_id: string }> {
  const validFiles = files.filter((file) => file instanceof File)
  if (!validFiles.length) {
    return { files: [], trace_id: String(traceId || '').trim() }
  }

  const body = new FormData()
  for (const file of validFiles) {
    body.append('files', file)
  }
  const safeTraceId = String(traceId || '').trim()
  if (safeTraceId) {
    body.append('trace_id', safeTraceId)
  }

  const res = await fetch(`${API_BASE}/api/files/upload`, {
    method: 'POST',
    body,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json()
}
