import type { NodeInfo, ProviderInfo } from '../../api'

const SUPPORT_MODE_ORDER = [
  'chat',
  'imagechat',
  'image_generation',
  'image_matting',
  'vision_understand',
  'video_generation',
  'video_change_person',
  'model_generation',
  'model_texture_generation',
  'audio_generation',
] as const

const SUPPORT_MODE_LABELS: Record<string, string> = {
}

export type NodeSupportModeGroup = {
  id: string
  label: string
  nodes: NodeInfo[]
}

export function groupNodesBySupportMode(nodes: NodeInfo[]): NodeSupportModeGroup[] {
  const groups = new Map<string, NodeSupportModeGroup>()
  for (const node of nodes) {
    const rawModes = Array.isArray(node.support_modes) ? node.support_modes : []
    const modes = rawModes.length ? rawModes : ['general']
    const seen = new Set<string>()
    for (const rawMode of modes) {
      const mode = String(rawMode || '').trim()
      const id = mode.toLowerCase()
      if (!id || seen.has(id)) continue
      seen.add(id)
      const group = groups.get(id) || {
        id,
        label: id === 'general' ? 'General' : (SUPPORT_MODE_LABELS[id] || mode),
        nodes: [],
      }
      group.nodes.push(node)
      groups.set(id, group)
    }
  }

  const order = new Map<string, number>(SUPPORT_MODE_ORDER.map((mode, index) => [mode, index]))
  return [...groups.values()].sort((left, right) => {
    const leftOrder = left.id === 'general'
      ? Number.MAX_SAFE_INTEGER
      : (order.get(left.id) ?? SUPPORT_MODE_ORDER.length)
    const rightOrder = right.id === 'general'
      ? Number.MAX_SAFE_INTEGER
      : (order.get(right.id) ?? SUPPORT_MODE_ORDER.length)
    return leftOrder - rightOrder || left.label.localeCompare(right.label)
  })
}

export function preferredProviderForSupportMode(providers: ProviderInfo[], supportMode: string) {
  const mode = String(supportMode || '').trim().toLowerCase()
  if (!mode || mode === 'general') return ''
  const provider = providers.find((item) => (
    Array.isArray(item.supportmode)
    && item.supportmode.some((value) => String(value || '').trim().toLowerCase() === mode)
  ))
  return String(provider?.id || '').trim()
}
