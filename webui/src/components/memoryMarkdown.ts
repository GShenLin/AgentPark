import katex from 'katex'
import { Marked, Renderer, marked, type MarkedExtension, type Tokens } from 'marked'
import markedKatex from 'marked-katex-extension'

const displayLatexRule = /^\\\[\s*([\s\S]*?)\s*\\\](?:\n|$)/
const inlineLatexRule = /^\\\((.+?)\\\)/

const standardLatexDelimiters: MarkedExtension = {
  extensions: [
    {
      name: 'displayLatex',
      level: 'block',
      start(src) {
        const index = src.indexOf('\\[')
        return index >= 0 ? index : undefined
      },
      tokenizer(src) {
        const match = src.match(displayLatexRule)
        if (!match) return undefined
        return {
          type: 'displayLatex',
          raw: match[0],
          text: String(match[1] || '').trim(),
          displayMode: true,
        }
      },
      renderer(token) {
        return `${katex.renderToString(String(token.text || ''), {
          displayMode: true,
          throwOnError: false,
        })}\n`
      },
    },
    {
      name: 'inlineLatex',
      level: 'inline',
      start(src) {
        const index = src.indexOf('\\(')
        return index >= 0 ? index : undefined
      },
      tokenizer(src) {
        const match = src.match(inlineLatexRule)
        if (!match) return undefined
        return {
          type: 'inlineLatex',
          raw: match[0],
          text: String(match[1] || '').trim(),
          displayMode: false,
        }
      },
      renderer(token) {
        return katex.renderToString(String(token.text || ''), {
          displayMode: false,
          throwOnError: false,
        })
      },
    },
  ],
}

marked.use(markedKatex({ throwOnError: false }))
marked.use(standardLatexDelimiters)
const liveMarked = new Marked()

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function languageClass(lang: string | undefined) {
  const value = String(lang || '').trim().split(/\s+/)[0]
  if (!value) return ''
  return ` class="language-${escapeHtml(value)}"`
}

function renderCodeBlock({ text, lang, escaped }: Tokens.Code) {
  const code = escaped ? text : escapeHtml(text)
  const className = languageClass(lang)
  return `<div class="markdown-code-block"><pre><code${className}>${code}</code></pre><button type="button" class="markdown-code-copy" aria-label="Copy code" title="Copy code">Copy</button></div>`
}

function isWindowsAbsolutePath(value: string) {
  return /^[a-zA-Z]:[\\/]/.test(value) || /^\\\\[^\\/]+[\\/][^\\/]+/.test(value)
}

export function resolveMarkdownImageHref(value: string) {
  const href = String(value || '').trim()
  if (!isWindowsAbsolutePath(href)) return href
  return `/api/files/raw?path=${encodeURIComponent(href)}`
}

function renderImage({ href, title, text }: Tokens.Image) {
  const resolvedHref = resolveMarkdownImageHref(href)
  const titleAttribute = title ? ` title="${escapeHtml(title)}"` : ''
  return `<img src="${escapeHtml(resolvedHref)}" alt="${escapeHtml(text)}"${titleAttribute}>`
}

function createMarkdownRenderer() {
  const renderer = new Renderer()
  renderer.code = renderCodeBlock
  renderer.image = renderImage
  return renderer
}

marked.use({ renderer: createMarkdownRenderer() })
liveMarked.use({ renderer: createMarkdownRenderer() })

function normalizeMemoryRole(role: string) {
  const value = String(role || '').trim().toLowerCase()
  if (!value) return 'other'
  if (value.includes('user') || value.includes('human')) return 'user'
  if (value.includes('assistant') || value.includes('agent')) return 'assistant'
  if (value.includes('system')) return 'system'
  if (value.includes('commentary') || value.includes('reasoning')) return 'commentary'
  if (value.includes('tool')) return 'tool'
  const safe = value.replace(/[^a-z0-9_-]/g, '')
  return safe || 'other'
}

function memoryRoleLabel(roleKey: string, rawRole: string) {
  if (roleKey === 'user') return 'User'
  if (roleKey === 'assistant') return 'Assistant'
  if (roleKey === 'system') return 'System'
  if (roleKey === 'commentary') return 'Commentary'
  if (roleKey === 'tool') return 'Tool'
  const text = String(rawRole || '').trim()
  return text || 'Other'
}

export function renderMarkdownText(text: string): string {
  const rendered = marked.parse(text, { async: false })
  return typeof rendered === 'string' ? rendered : text
}

export function renderMarkdownTextWithoutKatex(text: string): string {
  const rendered = liveMarked.parse(text, { async: false })
  return typeof rendered === 'string' ? rendered : text
}

function renderMemoryLogMarkdown(text: string) {
  const headerRe = /^\*\*\[([^\]]+)\]\s+(.+?)\*\*:\s?(.*)$/
  const rawLines = String(text || '').split(/\r?\n/)
  const blocks: Array<{ time: string; role: string; bodyLines: string[] }> = []
  let current: { time: string; role: string; bodyLines: string[] } | null = null

  const flush = () => {
    if (!current) return
    const hasContent = current.bodyLines.some((line) => String(line).trim().length > 0)
    if (hasContent) blocks.push(current)
    current = null
  }

  for (const line of rawLines) {
    const match = line.match(headerRe)
    if (match) {
      flush()
      current = { time: match[1] || '', role: match[2] || '', bodyLines: [] }
      if (match[3] != null && String(match[3]).length > 0) {
        current.bodyLines.push(String(match[3]))
      }
      continue
    }
    if (current) current.bodyLines.push(line)
  }
  flush()

  if (!blocks.length) return null

  const items = blocks
    .map((block) => {
      const roleKey = normalizeMemoryRole(block.role)
      const roleLabel = memoryRoleLabel(roleKey, block.role)
      const bodyMarkdown = block.bodyLines.join('\n').trim()
      const bodyHtml = bodyMarkdown ? renderMarkdownText(bodyMarkdown) : ''
      return `<div class="mem-msg mem-msg-${escapeHtml(roleKey)}"><div class="mem-msg-head"><span class="mem-role mem-role-${escapeHtml(roleKey)}">${escapeHtml(roleLabel)}</span><span class="mem-time">${escapeHtml(block.time)}</span></div><div class="mem-msg-body">${bodyHtml}</div></div>`
    })
    .join('')

  return `<div class="mem-log">${items}</div>`
}

export function renderMemoryMarkdown(text: string) {
  if (!text) return ''
  try {
    const memoryHtml = renderMemoryLogMarkdown(text)
    return memoryHtml ?? renderMarkdownText(text)
  } catch {
    return String(text)
  }
}
