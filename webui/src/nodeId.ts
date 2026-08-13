const WINDOWS_INVALID_NODE_ID_CHARACTERS = /[<>:"/\\|?*]/g

export function normalizeNodeId(value: unknown) {
  const raw = String(value ?? '').trim() || 'node'
  return raw.replace(WINDOWS_INVALID_NODE_ID_CHARACTERS, '_').trim() || 'node'
}

export function createUniqueNodeId(
  base: unknown,
  existingIds: Iterable<string>,
  excludeId = '',
) {
  const normalized = normalizeNodeId(base)
  const excluded = String(excludeId || '').trim()
  const occupied = new Set(
    Array.from(existingIds, (id) => String(id || '').trim()).filter((id) => id && id !== excluded),
  )
  if (!occupied.has(normalized)) return normalized

  let suffix = 1
  while (occupied.has(`${normalized}${suffix}`)) suffix += 1
  return `${normalized}${suffix}`
}
