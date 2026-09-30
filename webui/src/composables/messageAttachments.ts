import type { MessageEnvelope, ResourceKind } from '../api'

export type MessageAttachment = { name: string; path: string; kind?: string; mime?: string }
export type MessageResource = { uri: string; name: string; kind: ResourceKind; mime: string; source: string }

export function attachmentResource(file: MessageAttachment, source: string): MessageResource {
  const declared = file.kind as ResourceKind
  let kind: ResourceKind = 'file'
  if (['image', 'video', 'audio', 'doc', 'file', 'url'].includes(declared)) kind = declared
  else if (file.mime?.startsWith('image/') || /\.(png|jpg|jpeg|webp|gif|bmp|svg)$/i.test(file.path)) kind = 'image'
  else if (file.mime?.startsWith('audio/') || /\.(mp3|wav|ogg|flac|m4a)$/i.test(file.path)) kind = 'audio'
  else if (file.mime?.startsWith('video/') || /\.(mp4|mov|mkv|webm|avi|flv|m4v)$/i.test(file.path)) kind = 'video'
  else if (/\.(pdf|docx?|pptx?|xlsx?|txt|md)$/i.test(file.path)) kind = 'doc'
  return { uri: file.path, name: file.name, kind, mime: file.mime || '', source }
}

export function composeMessage(text: string, attachments: MessageAttachment[], source: string): string | MessageEnvelope {
  const trimmed = text.trim()
  if (!attachments.length && trimmed) return trimmed
  return { role: 'user', parts: [
    ...(trimmed ? [{ type: 'text' as const, text: trimmed }] : []),
    ...attachments.map(file => ({ type: 'resource' as const, resource: attachmentResource(file, source) })),
  ] }
}

export function isImageAttachment(file: MessageAttachment) {
  return attachmentResource(file, '').kind === 'image'
}

export function attachmentPreviewHref(file: MessageAttachment) {
  const raw = file.path.trim()
  if (/^(https?:|data:|blob:)/i.test(raw) || raw.startsWith('/api/files/raw')) return raw
  const normalized = raw.replace(/\\/g, '/')
  const index = normalized.toLowerCase().indexOf('/memories/')
  if (index >= 0) return normalized.slice(index)
  if (normalized.toLowerCase().startsWith('memories/')) return `/${normalized}`
  return `/api/files/raw?path=${encodeURIComponent(raw)}`
}
