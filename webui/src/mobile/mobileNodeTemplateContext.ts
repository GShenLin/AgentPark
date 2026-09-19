import type { MobileNode, ProviderInfo } from '../api'
import { resolveAgentProviderSchemaContext } from '../composables/useAgentNodeCreateSchema'

type NodeFields = Record<string, unknown>

export function resolveMobileNodeTemplateProviderId(
  providers: ProviderInfo[],
  fields: NodeFields | null | undefined,
) {
  return resolveAgentProviderSchemaContext(providers, fields).providerId
}

export function mobileNodeTemplateRequestKey(
  open: boolean,
  node: Pick<MobileNode, 'id' | 'type_id'> | null,
  config: NodeFields | null,
  providers: ProviderInfo[],
) {
  if (!open) return 'closed'
  const nodeId = String(node?.id || '').trim()
  const typeId = String(node?.type_id || '').trim()
  const providerId = resolveMobileNodeTemplateProviderId(providers, config)
  return `${nodeId}:${typeId}:${providerId}`
}
