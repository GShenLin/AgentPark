import type { MessageEnvelope, MessagePart } from '../api'
import { renderMarkdownText } from '../components/memoryMarkdown'

export function messageText(message: MessageEnvelope) {
  return (message.parts || [])
    .filter((part): part is Extract<MessagePart, { type: 'text' }> => part.type === 'text')
    .map((part) => String(part.text || ''))
    .join('\n')
    .trim()
}

export function buildMessageSignature(messages: MessageEnvelope[]) {
  return messages
    .map((message, index) => {
      const id = String(message.id || index)
      const role = String(message.role || '')
      const createdAt = String(message.created_at || '')
      const text = messageText(message)
      const parts = (message.parts || [])
        .map((part) => {
          if (part.type === 'resource') {
            const resource = part.resource || {}
            return `resource:${resource.uri || ''}:${resource.kind || ''}:${resource.mime || ''}`
          }
          return `${part.type}:${JSON.stringify(part).length}`
        })
        .join(',')
      return `${id}:${role}:${createdAt}:${text.length}:${parts}`
    })
    .join('|')
}

export function messageRoleClass(message: MessageEnvelope) {
  const role = String(message.role || '').toLowerCase()
  if (role.includes('user')) return 'from-user'
  if (role.includes('tool')) return 'from-tool'
  return 'from-node'
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function shouldRenderMarkdown(message: MessageEnvelope) {
  const role = String(message.role || '').toLowerCase()
  return !role.includes('user')
}

export function renderMessageMarkdown(message: MessageEnvelope) {
  const raw = messageText(message)
  if (!raw) return ''
  try {
    return renderMarkdownText(raw)
  } catch {
    return `<pre>${escapeHtml(raw)}</pre>`
  }
}
