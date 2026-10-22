export type ToolPromptDefinition = {
  name: string
  defaults: { source: string; description: string }[]
}
export type ToolPrompts = Record<string, string>
export const MAX_TOOL_PROMPT_CHARS = 32000

export function validToolPromptName(name: string): boolean {
  return /^[a-zA-Z0-9_-]+$/.test(name)
}

export function readToolPrompts(data: Record<string, unknown>): ToolPrompts | null {
  const value = data.tool_prompts
  if (value === undefined) return {}
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  if (Object.entries(value).some(([name, prompt]) => !validToolPromptName(name)
    || typeof prompt !== 'string' || prompt.length > MAX_TOOL_PROMPT_CHARS)) return null
  return value as ToolPrompts
}

export function setToolPrompt(data: Record<string, unknown>, name: string, prompt: string | null): Record<string, unknown> {
  const current = readToolPrompts(data)
  if (!current || !validToolPromptName(name)) throw new Error('Invalid tool prompt settings')
  const overrides = { ...current }
  if (prompt === null) delete overrides[name]
  else {
    if (prompt.length > MAX_TOOL_PROMPT_CHARS) throw new Error('Tool prompt is too long')
    // Computed properties also safely support tool names such as __proto__.
    return { ...data, tool_prompts: { ...overrides, [name]: prompt } }
  }
  return { ...data, tool_prompts: overrides }
}

export function toolPromptEntries(catalog: ToolPromptDefinition[], overrides: ToolPrompts): ToolPromptDefinition[] {
  const entries = new Map(catalog.map(item => [item.name, item]))
  for (const name of Object.keys(overrides)) {
    if (!entries.has(name)) entries.set(name, { name, defaults: [] })
  }
  return [...entries.values()].sort((a, b) => a.name.localeCompare(b.name))
}
