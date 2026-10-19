export type ToolDefinition = { id: string; name: string; description: string; module: string }
export type Toolset = { description: string; tools: string[] }
export type Toolsets = Record<string, Toolset>

export function readToolsets(data: Record<string, unknown>): Toolsets | null {
  if (data.deleted_toolsets !== undefined && (!Array.isArray(data.deleted_toolsets)
    || data.deleted_toolsets.some((name: unknown) => typeof name !== 'string'))) return null
  const sets = data.toolsets
  if (!sets || typeof sets !== 'object' || Array.isArray(sets)) return null
  if (Object.values(sets).some(value => !value || typeof value !== 'object'
    || typeof value.description !== 'string' || !Array.isArray(value.tools)
    || value.tools.some((tool: unknown) => typeof tool !== 'string'))) return null
  return sets as Toolsets
}

export function toggleTool(set: Toolset, reference: string, selected: boolean): Toolset {
  return { ...set, tools: selected ? [...new Set([...set.tools, reference])] : set.tools.filter(id => id !== reference) }
}

export function validToolsetId(id: string, sets: Toolsets): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(id) && !Object.prototype.hasOwnProperty.call(sets, id)
}
