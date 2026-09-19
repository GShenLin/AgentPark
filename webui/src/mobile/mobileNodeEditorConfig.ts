import { getNodeInstanceConfig, type NodeInstanceConfig } from '../api'

export async function loadMobileNodeEditorConfig(
  nodeId: string,
  graphId: string,
): Promise<NodeInstanceConfig> {
  const expectedNodeId = String(nodeId || '').trim()
  const expectedGraphId = String(graphId || '').trim()
  if (!expectedNodeId) throw new Error('Node id is required')
  if (!expectedGraphId) throw new Error('Graph id is required')

  const response = await getNodeInstanceConfig(expectedNodeId, expectedGraphId)
  const config = response.node
  const responseNodeId = String(config?.node_id || '').trim()
  const responseGraphId = String(config?.graph_id || '').trim()
  if (responseNodeId !== expectedNodeId || responseGraphId !== expectedGraphId) {
    throw new Error(
      `Node config response identity mismatch: expected ${expectedGraphId}/${expectedNodeId}, received ${responseGraphId || '<missing>'}/${responseNodeId || '<missing>'}`,
    )
  }
  return config
}
