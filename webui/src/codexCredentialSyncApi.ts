import { getActiveApiBase, requestApiJson } from './api'
import type { CodexAuthStatus } from './settingsApi'

export type CodexCredentialSyncResult = {
  accountId: string
  sourcePath: string
  status: CodexAuthStatus
}

export async function syncLocalCodexCredentials(accountId?: string): Promise<CodexCredentialSyncResult> {
  return requestApiJson(getActiveApiBase(), '/api/provider-auth/codex/sync-local', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accountId: accountId || null }),
  }) as Promise<CodexCredentialSyncResult>
}
