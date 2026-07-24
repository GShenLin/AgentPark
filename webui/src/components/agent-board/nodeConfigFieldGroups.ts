export type NodeConfigFieldSection = {
  id: string
  label: string
  collapsible: boolean
  defaultOpen: boolean
  keys: string[]
}

type NodeConfigSchema = Record<string, Record<string, unknown> | undefined>

const COMMON_AGENT_FIELDS = new Set([
  'provider_id',
  'instruction',
  'system_prompt',
  'working_path',
])

const SUPPORT_MODE_LABELS: Record<string, string> = {
  chat: 'Chat',
  image_generation: 'Image Generation',
  video_generation: 'Video Generation',
  audio_generation: 'Audio Generation',
  imagechat: 'Image Chat',
  vision_understand: 'Vision Understand',
}

function fieldModes(schema: NodeConfigSchema, key: string): string[] {
  const rawModes = schema[key]?.modes
  if (!Array.isArray(rawModes)) return []
  return rawModes
    .map((mode) => String(mode || '').trim())
    .filter(Boolean)
}

/**
 * Divide Agent configuration by its owning SupportMode.
 *
 * Provider selection lives in Common because it determines the complete
 * ordered SupportMode set. A node never selects one current SupportMode.
 */
export function createNodeConfigFieldSections(
  typeId: string,
  schemaKeys: string[],
  schema: NodeConfigSchema = {},
  supportModes: string[] = [],
): NodeConfigFieldSection[] {
  if (String(typeId || '').trim() !== 'agent_node') {
    return schemaKeys.length
      ? [{ id: 'fields', label: '', collapsible: false, defaultOpen: true, keys: [...schemaKeys] }]
      : []
  }

  const visibleKeys = [...schemaKeys]
  const commonKeys: string[] = []
  const modeGroups = new Map<string, { modes: string[]; keys: string[] }>()
  for (const key of visibleKeys) {
    const modes = fieldModes(schema, key)
    if (COMMON_AGENT_FIELDS.has(key) || modes.length === 0 || modes.includes('*')) {
      commonKeys.push(key)
    } else {
      const owners = supportModes.filter((mode) => modes.includes(mode))
      if (!owners.length) continue
      const signature = owners.join('|')
      const group = modeGroups.get(signature) || { modes: owners, keys: [] }
      group.keys.push(key)
      modeGroups.set(signature, group)
    }
  }

  const sections: NodeConfigFieldSection[] = []
  if (commonKeys.length) {
    sections.push({
      id: 'common',
      label: 'Common',
      collapsible: true,
      defaultOpen: true,
      keys: commonKeys,
    })
  }
  const orderedModeGroups = [...modeGroups.values()].sort((left, right) => (
    supportModes.indexOf(left.modes[0] || '') - supportModes.indexOf(right.modes[0] || '')
  ))
  for (const group of orderedModeGroups) {
    sections.push({
      id: `support-mode:${group.modes.join('+')}`,
      label: group.modes.map((mode) => SUPPORT_MODE_LABELS[mode] || mode).join(' / '),
      collapsible: true,
      defaultOpen: true,
      keys: group.keys,
    })
  }
  return sections
}
