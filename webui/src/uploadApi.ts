import { createApiNetworkError, getActiveApiBase } from './api'

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

  const baseUrl = getActiveApiBase()
  const path = '/api/files/upload'
  const init: RequestInit = {
    method: 'POST',
    body,
  }
  let res: Response
  try {
    res = await fetch(`${baseUrl}${path}`, init)
  } catch (error) {
    throw createApiNetworkError(baseUrl, path, init, error)
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json()
}
