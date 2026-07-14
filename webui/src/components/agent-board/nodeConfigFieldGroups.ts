export type NodeConfigFieldGroupId = 'environment' | 'behavior' | 'ability'

export type NodeConfigFieldSection = {
  id: string
  label: string
  collapsible: boolean
  keys: string[]
}

type NodeConfigFieldGroupDefinition = {
  id: NodeConfigFieldGroupId
  label: string
  keys: readonly string[]
}

const agentNodeFieldGroups: readonly NodeConfigFieldGroupDefinition[] = [
  {
    id: 'environment',
    label: 'Environment',
    keys: ['provider_id', 'instruction', 'system_prompt', 'working_path'],
  },
  {
    id: 'behavior',
    label: 'Behavior',
    keys: ['mode', 'collaboration_mode', 'web_search', 'thinking', 'reasoning_effort', 'reasoning_summary'],
  },
  {
    id: 'ability',
    label: 'Ability',
    keys: ['skills', 'tools', 'mcp_servers', 'plugins'],
  },
]

export function createNodeConfigFieldSections(typeId: string, schemaKeys: string[]): NodeConfigFieldSection[] {
  if (String(typeId || '').trim() !== 'agent_node') {
    return schemaKeys.length
      ? [{ id: 'fields', label: '', collapsible: false, keys: [...schemaKeys] }]
      : []
  }

  const availableKeys = new Set(schemaKeys)
  const groupedKeys = new Set(agentNodeFieldGroups.flatMap((group) => group.keys))
  const sections: NodeConfigFieldSection[] = []
  const ungroupedKeys = schemaKeys.filter((key) => !groupedKeys.has(key))

  if (ungroupedKeys.length) {
    sections.push({
      id: 'fields',
      label: '',
      collapsible: false,
      keys: ungroupedKeys,
    })
  }

  for (const group of agentNodeFieldGroups) {
    const keys = group.keys.filter((key) => availableKeys.has(key))
    if (!keys.length) continue
    sections.push({
      id: group.id,
      label: group.label,
      collapsible: true,
      keys,
    })
  }

  return sections
}
