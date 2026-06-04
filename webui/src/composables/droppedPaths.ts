import { uploadFiles } from '../uploadApi'

export type DroppedPathItem = {
  name: string
  path: string
}

export const ASSET_FIELD_KEYS = new Set([
  'image_path',
  'video_path',
  'first_frame_path',
  'last_frame_path',
  'reference_images',
  'reference_videos',
  'reference_audios',
  'images',
  'model_path',
])

function normalizeDroppedItem(path: string, name = ''): DroppedPathItem | null {
  const safePath = String(path || '').trim()
  if (!safePath) return null
  return {
    path: safePath,
    name: String(name || '').trim() || safePath,
  }
}

function parseInternalDroppedItem(raw: string): DroppedPathItem | null {
  try {
    const data = JSON.parse(raw)
    return normalizeDroppedItem(String(data?.path || ''), String(data?.name || ''))
  } catch {
    return null
  }
}

export async function resolveDroppedPaths(event: DragEvent, traceId: string): Promise<DroppedPathItem[]> {
  const raw = event.dataTransfer?.getData('application/x-aitools-file')
  if (raw) {
    const internalItem = parseInternalDroppedItem(raw)
    return internalItem ? [internalItem] : []
  }

  const nativeFiles = Array.from(event.dataTransfer?.files || []).filter((file) => file instanceof File)
  if (!nativeFiles.length) return []

  const uploaded = await uploadFiles(nativeFiles, traceId)
  const items = Array.isArray(uploaded?.files) ? uploaded.files : []
  return items
    .map((item) => normalizeDroppedItem(String(item?.path || ''), String(item?.name || '')))
    .filter((item): item is DroppedPathItem => !!item)
}

export function mergeDroppedPaths(fieldType: string, currentValue: unknown, droppedItems: DroppedPathItem[]): string {
  const nextPaths = droppedItems.map((item) => item.path).filter(Boolean)
  if (!nextPaths.length) {
    return String(currentValue ?? '')
  }

  if (fieldType === 'string') {
    return nextPaths[0] || ''
  }

  const existingLines = String(currentValue ?? '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  const seen = new Set(existingLines.map((line) => line.toLowerCase()))
  const merged = [...existingLines]
  for (const path of nextPaths) {
    const key = path.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(path)
  }
  return merged.join('\n')
}
