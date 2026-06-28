import type { Ref } from 'vue'
import type { NodeInstanceConfig, NodeInstanceState } from '../../api'
import type { LinkItem, NodeCard, NodeRunState } from './context'

export function renameBoardNodeIdentity(options: {
  oldId: string
  newId: string
  nodes: Ref<NodeCard[]>
  links: Ref<LinkItem[]>
  selectedNodeId: Ref<string | null>
  selectedItemIds: Ref<string[]>
  nodeConfigs: Ref<Record<string, NodeInstanceConfig>>
  nodeStates: Ref<Record<string, NodeInstanceState>>
  nodeRuns: Ref<Record<string, NodeRunState>>
  nodeDonePulse: Ref<Record<string, number>>
}) {
  const node = options.nodes.value.find((item) => item.id === options.oldId)
  if (node) {
    node.id = options.newId
    node.name = options.newId
  }

  if (options.selectedNodeId.value === options.oldId) options.selectedNodeId.value = options.newId
  options.selectedItemIds.value = options.selectedItemIds.value.map((id) => (id === options.oldId ? options.newId : id))

  for (const link of options.links.value) {
    if (link.from.node === options.oldId) link.from.node = options.newId
    if (link.to.node === options.oldId) link.to.node = options.newId
  }

  options.nodeConfigs.value = renameNodeConfigRecord(options.nodeConfigs.value, options.oldId, options.newId)
  options.nodeStates.value = renameRecordKey(options.nodeStates.value, options.oldId, options.newId)
  options.nodeRuns.value = renameNodeRunRecord(options.nodeRuns.value, options.oldId, options.newId)
  options.nodeDonePulse.value = renameRecordKey(options.nodeDonePulse.value, options.oldId, options.newId)
}

export function removeBoardNodeRuntimeState(options: {
  nodeId: string
  nodeStates: Ref<Record<string, NodeInstanceState>>
  nodeDonePulse: Ref<Record<string, number>>
  nodeRuns: Ref<Record<string, NodeRunState>>
}) {
  const nextStates = { ...options.nodeStates.value }
  delete nextStates[options.nodeId]
  options.nodeStates.value = nextStates

  const nextDone = { ...options.nodeDonePulse.value }
  delete nextDone[options.nodeId]
  options.nodeDonePulse.value = nextDone

  options.nodeRuns.value = Object.fromEntries(
    Object.entries(options.nodeRuns.value).filter(([, run]) => run.nodeId !== options.nodeId),
  )
}

function renameNodeConfigRecord(
  records: Record<string, NodeInstanceConfig>,
  oldId: string,
  newId: string,
) {
  const prev = records[oldId]
  const next = { ...records }
  delete next[oldId]
  if (prev) {
    next[newId] = {
      ...prev,
      node_id: newId,
      name: newId,
    } as NodeInstanceConfig
  }
  return next
}

function renameNodeRunRecord(
  records: Record<string, NodeRunState>,
  oldId: string,
  newId: string,
) {
  const prev = records[oldId]
  const next = { ...records }
  delete next[oldId]
  if (prev) {
    next[newId] = { ...prev, nodeId: newId }
  }
  return next
}

function renameRecordKey<T>(records: Record<string, T>, oldId: string, newId: string) {
  const prev = records[oldId]
  const next = { ...records }
  delete next[oldId]
  if (prev !== undefined) next[newId] = prev
  return next
}
