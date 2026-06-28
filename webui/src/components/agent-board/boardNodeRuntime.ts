import type { NodeInstanceConfig, NodeInstanceState } from '../../api'
import type { NodeCard } from './context'
import { sleep } from './boardModel'

export type BoardNodeOutputWaitResult = {
  status: 'completed' | 'stopped' | 'deadline'
  message: string
}

export async function waitForBoardNodeOutput(options: {
  nodeId: string
  prevRunAt: string | null
  prevMessage: string | null
  graphId: string
  listNodeInstanceConfigs: (graphId: string) => Promise<unknown>
  timeoutMs?: number
  pollMs?: number
}): Promise<BoardNodeOutputWaitResult> {
  const timeoutMs = options.timeoutMs ?? 60_000
  const pollMs = options.pollMs ?? 250
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const response = await options.listNodeInstanceConfigs(options.graphId).catch(() => null)
    const items = Array.isArray(response) ? response : (response as any)?.nodes
    const cfg = Array.isArray(items)
      ? (items as any[]).find((item) => String(item?.node_id || '') === options.nodeId)
      : null
    if (!cfg) {
      await sleep(pollMs)
      continue
    }
    const state = String(cfg.state || 'idle')
    if (state === 'stop') return { status: 'stopped', message: '' }
    const runAt = String(cfg.last_run_at ?? '')
    const message = String(cfg.last_message ?? '')
    const pendingCount = Number((cfg as any)?.pending_count ?? 0)
    const hasInflight = !!(cfg as any)?.inflight
    const busy = state === 'working' || pendingCount > 0 || hasInflight
    if (runAt && (!options.prevRunAt || runAt !== options.prevRunAt)) {
      return { status: 'completed', message }
    }
    if (!runAt && !busy && message.trim() && message !== String(options.prevMessage ?? '')) {
      return { status: 'completed', message }
    }
    await sleep(pollMs)
  }
  return { status: 'deadline', message: '' }
}

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
