import type { MessageEnvelope } from '../api'
import { extractResponseMetadataInsights } from '../utils/responseMetadataInsights'
import type { ParsedFilePatch } from '../utils/responseMetadataDiff'
import { isResponseMetadataPart, messageParts, responseMetadataPartData } from './memoryFeedTools'

export type LocalFileLink = {
  path: string
  href: string
}

function safeDecode(value: string) {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

function stripSourceLocation(path: string) {
  return path
    .replace(/#L\d+(?:C\d+)?$/i, '')
    .replace(/:(\d+)(?::\d+)?$/, '')
}

function fileUriPath(href: string) {
  try {
    const url = new URL(href)
    let path = safeDecode(url.pathname)
    if (url.hostname) path = `//${url.hostname}${path}`
    if (/^\/[A-Za-z]:\//.test(path)) path = path.slice(1)
    return stripSourceLocation(path)
  } catch {
    return ''
  }
}

export function localFileLinkFromAnchor(anchor: HTMLAnchorElement): LocalFileLink | null {
  const href = String(anchor.getAttribute('href') || '').trim()
  if (!href || href.startsWith('#')) return null
  if (/^(https?|mailto|tel|data|blob|javascript):/i.test(href)) return null

  if (/^file:/i.test(href)) {
    const path = fileUriPath(href)
    return path ? { path, href } : null
  }

  if (href.startsWith('/api/files/raw')) {
    try {
      const url = new URL(href, window.location.origin)
      const path = String(url.searchParams.get('path') || '').trim()
      return path ? { path, href } : null
    } catch {
      return null
    }
  }

  if (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(href) && !/^[A-Za-z]:[\\/]/.test(href)) return null
  const path = stripSourceLocation(safeDecode(href.split(/[?#]/, 1)[0] || ''))
  return path ? { path, href } : null
}

function normalizedPath(value: string) {
  return stripSourceLocation(safeDecode(String(value || '').trim()))
    .replace(/\\/g, '/')
    .replace(/^\.\//, '')
    .replace(/\/{2,}/g, '/')
    .replace(/\/$/, '')
    .toLowerCase()
}

function basename(value: string) {
  const normalized = normalizedPath(value)
  return normalized.slice(normalized.lastIndexOf('/') + 1)
}

export function collectMessageFilePatches(message: MessageEnvelope): ParsedFilePatch[] {
  const output: ParsedFilePatch[] = []
  const seen = new Set<string>()
  for (const part of messageParts(message)) {
    if (!isResponseMetadataPart(part)) continue
    const data = responseMetadataPartData(part) || {}
    const metadata = data.response_metadata && typeof data.response_metadata === 'object'
      ? data.response_metadata
      : data
    const insights = extractResponseMetadataInsights(metadata)
    for (const change of Array.isArray(insights.file_changes) ? insights.file_changes : []) {
      for (const patch of Array.isArray(change.patches) ? change.patches as ParsedFilePatch[] : []) {
        const key = `${patch.operation}\u0000${normalizedPath(patch.path)}\u0000${patch.rawPatch}`
        if (seen.has(key)) continue
        seen.add(key)
        output.push(patch)
      }
    }
  }
  return output
}

export function matchingFilePatches(path: string, patches: ParsedFilePatch[]) {
  const target = normalizedPath(path)
  if (!target) return []

  const pathMatches = patches.filter((patch) => {
    const candidate = normalizedPath(patch.path)
    return candidate === target
      || target.endsWith(`/${candidate}`)
      || candidate.endsWith(`/${target}`)
  })
  if (pathMatches.length) return pathMatches

  const targetBasename = basename(target)
  const basenameMatches = patches.filter((patch) => basename(patch.path) === targetBasename)
  return basenameMatches.length === 1 ? basenameMatches : []
}

