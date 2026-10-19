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

const VOICE_FIELDS = new Set(['voice_provider_id', 'voice_model', 'voice'])

const CAPABILITY_SECTIONS = [
  { key: 'tools', label: 'Tool' },
  { key: 'mcp_servers', label: 'MCP' },
  { key: 'skills', label: 'Skill' },
  { key: 'plugins', label: 'Plugin' },
] as const

const SUPPORT_MODE_LABELS: Record<string, string> = {
  chat: 'Chat',
  image_generation: 'Image Generation',
  video_generation: 'Video Generation',
  audio_generation: 'Audio Generation',
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
 * Divide Agent configuration by SupportMode and independent capabilities.
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
  const voiceKeys: string[] = []
  const capabilityKeys = new Set<string>()
  const modeGroups = new Map<string, { modes: string[]; keys: string[] }>()
  for (const key of visibleKeys) {
    if (VOICE_FIELDS.has(key)) {
      voiceKeys.push(key)
      continue
    }
    const modes = fieldModes(schema, key)
    if (CAPABILITY_SECTIONS.some(section => section.key === key)) {
      if (modes.length === 0 || modes.includes('*') || modes.some(mode => supportModes.includes(mode))) {
        capabilityKeys.add(key)
      }
      continue
    }
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
      defaultOpen: false,
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
      defaultOpen: false,
      keys: group.keys,
    })
  }
  for (const section of CAPABILITY_SECTIONS) {
    if (!capabilityKeys.has(section.key)) continue
    sections.push({
      id: `capability:${section.key}`, label: section.label,
      collapsible: true, defaultOpen: false, keys: [section.key],
    })
  }
  if (voiceKeys.length) {
    sections.push({
      id: 'voice', label: '语音设置', collapsible: true, defaultOpen: false, keys: voiceKeys,
    })
  }
  return sections
}
