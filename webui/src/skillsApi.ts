import { getActiveApiBase, requestApiJson } from './api'

export interface SkillEntry {
  root_id: string; shadowed_by: string
  path: string; parent: string; kind: 'folder' | 'skill'; name: string; description: string
  version: string; error: string; skill_count: number; folder_count: number; used_by: string[]
}
export interface SkillSource {
  id: string; path: string; kind: 'project' | 'user' | 'custom'; label: string
  entries: SkillEntry[]; trash: { id: string; path: string }[]; exists: boolean; error: string
}
export interface SkillCatalog {
  sources: SkillSource[]; usage_error: string
}
export interface SkillDetail {
  path: string; content: string; error: string; tools: string[]; mcp_servers: string[]
  resources: { type: string; path: string; title: string; size_bytes: number; summary: string }[]
}
export type SkillOperation = { root_id: string } & (
  | { action: 'create_folder'; parent: string; name: string }
  | { action: 'move'; path: string; parent: string; name: string }
  | { action: 'delete'; path: string }
  | { action: 'restore'; trash_id: string })

export const listSkills = (): Promise<SkillCatalog> => requestApiJson(getActiveApiBase(), '/api/skills')
export const getSkillDetail = (rootId: string, path: string): Promise<SkillDetail> => requestApiJson(
  getActiveApiBase(), `/api/skills/detail?root_id=${encodeURIComponent(rootId)}&path=${encodeURIComponent(path)}`,
)
export const configureSkillRoots = (operation: { action: 'add'; path: string } | { action: 'remove'; root_id: string }): Promise<{ ok: boolean }> => requestApiJson(
  getActiveApiBase(), '/api/skills/roots', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(operation),
  },
)
export const operateSkill = (operation: SkillOperation): Promise<{ ok: boolean }> => requestApiJson(
  getActiveApiBase(), '/api/skills/operations', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(operation),
  },
)

export function skillView(entries: SkillEntry[], folder: string, query: string): SkillEntry[] {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  return entries.filter(entry => words.length
    ? words.every(word => `${entry.name} ${entry.description} ${entry.path}`.toLocaleLowerCase().includes(word))
    : entry.parent === folder,
  ).sort((a, b) => Number(a.kind === 'skill') - Number(b.kind === 'skill') || a.name.localeCompare(b.name))
}

export function moveTargets(entries: SkillEntry[], source: string): SkillEntry[] {
  return entries.filter(entry => entry.kind === 'folder' && !entry.error && entry.path !== source && !entry.path.startsWith(`${source}/`))
}
