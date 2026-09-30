import { describe, expect, it } from 'vitest'
import { graphHierarchy } from './graphHierarchy'
import type { NodeInstanceConfig } from '../../api'
import type { AgentGroup } from '../../groups/groupApi'

const node = (id: string) => ({ node_id: id, name: id, type_id: 'agent_node' }) as NodeInstanceConfig
const group = (id: string, ids: string[]) => ({ id, members: ids.map(node_id => ({ node_id, role: '' })) }) as AgentGroup

describe('Graph hierarchy', () => {
  it('places members under their Group exactly once, retaining ungrouped nodes', () => {
    const tree = graphHierarchy([node('ui'), node('animation'), node('tools')], [group('team', ['ui', 'animation'])])
    expect(tree.groups[0]!.members.map(member => member.node?.node_id)).toEqual(['ui', 'animation'])
    expect(tree.ungrouped.map(node => node.node_id)).toEqual(['tools'])
  })
  it('returns former members to the Graph after dissolution and never borrows another Graph’s nodes', () => {
    expect(graphHierarchy([node('ui')], []).ungrouped).toHaveLength(1)
    const other = graphHierarchy([node('worker')], [group('team', ['missing'])])
    expect(other.groups[0]!.members[0]!.node).toBeUndefined()
    expect(other.ungrouped.map(node => node.node_id)).toEqual(['worker'])
  })
})
