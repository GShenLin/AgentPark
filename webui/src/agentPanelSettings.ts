export type AgentPanelSettings = {
  width: number
  height: number
}

export const DEFAULT_AGENT_PANEL_SETTINGS: AgentPanelSettings = { width: 1040, height: 820 }

export function normalizeAgentPanelSettings(value: unknown): AgentPanelSettings {
  if (value === undefined || value === null) return { ...DEFAULT_AGENT_PANEL_SETTINGS }
  if (typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('agentPanel must be an object')
  }
  const settings = value as Record<string, unknown>
  function dimension(key: keyof AgentPanelSettings, minimum: number): number {
    const number = settings[key] === undefined ? DEFAULT_AGENT_PANEL_SETTINGS[key] : settings[key]
    if (typeof number !== 'number' || !Number.isInteger(number) || number < minimum || number > 7680) {
      throw new Error(`agentPanel.${key} must be an integer between ${minimum} and 7680`)
    }
    return number
  }
  return { width: dimension('width', 360), height: dimension('height', 320) }
}
