import { ApiHttpError, getActiveApiBase, requestApiJson } from './api'

export interface KnowledgeConfig {
  name: string; folder: string; embedding_url: string; embedding_model: string; dimensions: number
  api_key_alias: string; batch_size: number; chunk_size: number; chunk_overlap: number
  request_timeout: number; retry_interval_seconds: number; max_file_mb: number; max_page_chars: number; spreadsheet_header_row: number; allow_agents: boolean
}
export interface KnowledgeProgress {
  status: string; phase: string; discovered: number; excluded: number; current_path: string; error: string
  documents: Record<string, number>; chunks: Record<string, number>; index_bytes: number
}
export interface KnowledgeLibrary extends KnowledgeConfig {
  id: string; has_api_key: boolean; progress: KnowledgeProgress
}
export interface KnowledgeDocument {
  id: number; path: string; state: string; error: string; warning: string; chunk_count: number
}
export interface KnowledgeHit {
  chunk_id: number; document_id: number; text: string; page: number | null; line: number | null
  path: string; score: number; channels: string[]; warning: string; document_state: string
  location: { kind?: 'word' | 'spreadsheet'; part?: string; section?: string; paragraph?: number;
    table?: number; nested_row?: number; sheet?: string; row_start?: number; row_end?: number;
    column_start?: string; column_end?: string }
}
export function knowledgeCitation(hit: KnowledgeHit): string {
  const location = hit.location
  if (location?.kind === 'spreadsheet') return `${location.sheet} · ${location.column_start}${location.row_start}:${location.column_end}${location.row_end}`
  if (location?.kind === 'word') return [location.part, location.section,
    location.table ? `表 ${location.table} 第 ${location.row_start} 行` : `第 ${location.paragraph} 段`,
    location.nested_row ? `嵌套表第 ${location.nested_row} 行` : ''].filter(Boolean).join(' · ')
  return hit.page ? `第 ${hit.page} 页` : hit.line ? `第 ${hit.line} 行` : '文档片段'
}
export interface KnowledgeSearch {
  matches: KnowledgeHit[]; partial: boolean; index_status: string; coverage: Record<string, number>
}
export type KnowledgeAction = 'scan' | 'pause' | 'resume' | 'retry'
export const emptyKnowledgeConfig = (): KnowledgeConfig => ({
  name: '', folder: '', embedding_url: 'http://localhost:11434/v1/embeddings', embedding_model: '',
  dimensions: 1024, api_key_alias: '', batch_size: 32, chunk_size: 1600, chunk_overlap: 200,
  request_timeout: 60, retry_interval_seconds: 5, max_file_mb: 256, max_page_chars: 200000, spreadsheet_header_row: 0, allow_agents: true,
})
export async function knowledgeRequest<T>(path = '', method = 'GET', body?: unknown): Promise<T> {
  try {
    return await requestApiJson(getActiveApiBase(), `/api/knowledge${path}`, {
      method, ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    })
  } catch (error) {
    if (error instanceof ApiHttpError && error.status === 422) {
      let details: unknown
      try { details = JSON.parse(error.detail) } catch { throw error }
      if (Array.isArray(details) && details.length && details.every(item =>
        item && typeof item.msg === 'string' && Array.isArray(item.loc))) {
        throw new Error(details.map(item => `${item.loc.slice(1).join('.')}: ${item.msg}`).join('\n'))
      }
    }
    throw error
  }
}
export const listKnowledge = () => knowledgeRequest<{ libraries: KnowledgeLibrary[]; worker_error: string }>()
export const saveKnowledge = (config: KnowledgeConfig, id = '') => knowledgeRequest<KnowledgeLibrary>(
  id ? `/${encodeURIComponent(id)}` : '', id ? 'PUT' : 'POST', config,
)
export const operateKnowledge = (id: string, action: KnowledgeAction) => knowledgeRequest<KnowledgeProgress>(
  `/${encodeURIComponent(id)}/operations`, 'POST', { action },
)
export const testKnowledge = (id: string) => knowledgeRequest<{ ok: boolean; dimensions: number }>(`/${encodeURIComponent(id)}/test`, 'POST')
export const listKnowledgeDocuments = (id: string, after = 0, state = '') => knowledgeRequest<{
  items: KnowledgeDocument[]; next_cursor: number | null
}>(`/${encodeURIComponent(id)}/documents?after=${after}&state=${encodeURIComponent(state)}`)
export const searchKnowledge = (id: string, query: string, mode: string) => knowledgeRequest<KnowledgeSearch>(
  `/${encodeURIComponent(id)}/search`, 'POST', { query, mode, limit: 10 },
)
