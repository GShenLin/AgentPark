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
  'image_references',
  'reference_images',
  'reference_videos',
  'reference_audios',
  'audio_references',
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

function uploadResultToDroppedItems(uploaded: unknown): DroppedPathItem[] {
  const items = Array.isArray((uploaded as any)?.files) ? (uploaded as any).files : []
  return items
    .map((item: any) => normalizeDroppedItem(String(item?.path || ''), String(item?.name || '')))
    .filter((item: DroppedPathItem | null): item is DroppedPathItem => !!item)
}

export async function resolveDroppedPaths(event: DragEvent, traceId: string): Promise<DroppedPathItem[]> {
  const raw = event.dataTransfer?.getData('application/x-agentpark-file')
  if (raw) {
    const internalItem = parseInternalDroppedItem(raw)
    return internalItem ? [internalItem] : []
  }

  const nativeFiles = Array.from(event.dataTransfer?.files || []).filter((file) => file instanceof File)
  if (!nativeFiles.length) return []

  const uploaded = await uploadFiles(nativeFiles, traceId)
  return uploadResultToDroppedItems(uploaded)
}

export async function resolvePastedImagePaths(event: ClipboardEvent, traceId: string): Promise<DroppedPathItem[]> {
  const clipboardItems = Array.from(event.clipboardData?.items || [])
  const imageFiles = clipboardItems
    .filter((item) => item.kind === 'file' && item.type.toLowerCase().startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter((file): file is File => file instanceof File)

  if (!imageFiles.length) return []

  const files = imageFiles.map((file, index) => {
    if (String(file.name || '').trim()) return file
    const ext = file.type.split('/')[1]?.split('+')[0] || 'png'
    return new File([file], `pasted-image-${Date.now()}-${index + 1}.${ext}`, { type: file.type })
  })

  const uploaded = await uploadFiles(files, traceId)
  return uploadResultToDroppedItems(uploaded)
}

export function normalizePathList(value: unknown): string[] {
  let rawValues: unknown[]
  if (Array.isArray(value)) {
    rawValues = value
  } else {
    const textValue = String(value ?? '').trim()
    if (!textValue) return []
    if (textValue.startsWith('[')) {
      try {
        const parsed = JSON.parse(textValue)
        rawValues = Array.isArray(parsed) ? parsed : [textValue]
      } catch {
        rawValues = textValue.split(/\r?\n/)
      }
    } else {
      rawValues = textValue.split(/\r?\n/)
    }
  }

  const paths: string[] = []
  const seen = new Set<string>()
  for (const item of rawValues) {
    const path = String(item ?? '').trim()
    if (!path) continue
    const key = path.replace(/[\\/]+/g, '/').toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    paths.push(path)
  }
  return paths
}

export function mergeDroppedPaths(fieldType: string, currentValue: unknown, droppedItems: DroppedPathItem[]): string | string[] {
  const nextPaths = droppedItems.map((item) => item.path).filter(Boolean)
  if (!nextPaths.length) {
    return fieldType === 'file_list' ? normalizePathList(currentValue) : String(currentValue ?? '')
  }

  if (fieldType === 'string') {
    return nextPaths[0] || ''
  }

  const existingLines = normalizePathList(currentValue)
  const seen = new Set(existingLines.map((line) => line.toLowerCase()))
  const merged = [...existingLines]
  for (const path of nextPaths) {
    const key = path.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(path)
  }
  return fieldType === 'file_list' ? merged : merged.join('\n')
}
