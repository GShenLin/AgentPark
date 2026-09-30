import type { NodeInstanceConfig } from '../../api'
import type { AgentGroup } from '../../groups/groupApi'

/** Nodes belong to the Graph; group membership determines their one tree location. */
export function graphHierarchy(nodes: NodeInstanceConfig[], groups: AgentGroup[]) {
  const byId = new Map(nodes.map(node => [node.node_id, node]))
  const memberIds = new Set(groups.flatMap(group => group.members.map(member => member.node_id)))
  return {
    groups: groups.map(group => ({ group, members: group.members.map(member => ({
      ...member, node: byId.get(member.node_id),
    })) })),
    ungrouped: nodes.filter(node => !memberIds.has(node.node_id)),
  }
}
