import { getActiveApiBase, requestApiJson } from './api'

export interface LocalServiceConfig {
  name: string; kind: 'strata' | 'comfyui'; install_path: string; python_path: string
  endpoint: string; workflow_path: string; extra_args: string[]
}
export interface LocalService extends LocalServiceConfig { id: string }
export interface LocalModel {
  id: string; name: string; category: string; path: string; available: boolean; missing: string[]; bytes: number | null
}
export interface LocalStatus {
  installed: boolean; online: boolean; loaded: boolean | null; active_model: string | null
  models: LocalModel[]; issues: string[]; connection_error: string; python_path: string
  python_exists: boolean; managed: boolean; detail: Record<string, unknown> | null
}
export interface LocalJob {
  id: string; service_id: string; action: string; state: 'running' | 'succeeded' | 'failed'; message: string
}
export interface LocalOperation {
  action: 'start' | 'stop' | 'load' | 'unload' | 'import'; model_id?: string; source_path?: string; category?: string
}
export async function localModelRequest<T>(path = '', method = 'GET', body?: unknown): Promise<T> {
  return requestApiJson(getActiveApiBase(), `/api/local-model${path}`, {
    method, ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  }) as Promise<T>
}
export const emptyLocalService = (): LocalServiceConfig => ({
  name: 'Strata', kind: 'strata', install_path: '', python_path: '',
  endpoint: 'http://127.0.0.1:8080', workflow_path: '', extra_args: [],
})
