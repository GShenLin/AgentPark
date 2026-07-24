import type { NodeInstanceConfig, NodeInstanceState } from '../../api'
import type { NodeCard } from './context'

export function getBoardNodeState(
  nodeStates: Record<string, NodeInstanceState>,
  nodeId: string,
): NodeInstanceState {
  return nodeStates[nodeId] || 'idle'
}

export function isBoardNodeWorking(
  nodeStates: Record<string, NodeInstanceState>,
  nodeId: string,
) {
  return getBoardNodeState(nodeStates, nodeId) === 'working'
}

export function isBoardNodeStopped(
  nodeStates: Record<string, NodeInstanceState>,
  nodeId: string,
) {
  return getBoardNodeState(nodeStates, nodeId) === 'stop'
}

export function resolveBoardNodeTypeId(options: {
  nodeConfigs: Record<string, NodeInstanceConfig>
  nodes: NodeCard[]
  nodeId: string
}) {
  const cfg = options.nodeConfigs[options.nodeId]
  return String(cfg?.type_id || options.nodes.find((node) => node.id === options.nodeId)?.typeId || '').trim()
}

export function isBoardClockNode(options: {
  nodeConfigs: Record<string, NodeInstanceConfig>
  nodes: NodeCard[]
  nodeId: string
}) {
  return resolveBoardNodeTypeId(options) === 'clock_node'
}

export function isBoardClockRunning(options: {
  nodeConfigs: Record<string, NodeInstanceConfig>
  nodes: NodeCard[]
  nodeId: string
}) {
  if (!isBoardClockNode(options)) return false
  return !!options.nodeConfigs[options.nodeId]?.['_clock_running']
}
