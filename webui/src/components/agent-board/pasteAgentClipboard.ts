import type { MessageEnvelope } from '../../api'
import type { DroppedPathItem } from '../../composables/droppedPaths'

export function buildPasteAgentMessage(
  rawText: string,
  images: DroppedPathItem[],
): string | MessageEnvelope {
  const text = String(rawText || '').trim()
  if (!images.length) return text

  const parts: MessageEnvelope['parts'] = []
  if (text) {
    parts.push({ type: 'text', text })
  }
  for (const image of images) {
    const uri = String(image.path || '').trim()
    if (!uri) continue
    parts.push({
      type: 'resource',
      resource: {
        uri,
        name: String(image.name || '').trim(),
        kind: 'image',
        source: 'paste_agent',
      },
    })
  }
  return { role: 'user', parts }
}
