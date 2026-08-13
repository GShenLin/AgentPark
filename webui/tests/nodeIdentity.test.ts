import { describe, expect, it } from 'vitest'
import type { GraphConfig, MobileNode, NodeInstanceConfig } from '../src/api'
import { renameMobileNodeIdentity } from '../src/mobile/mobileNodeIdentity'
import { createUniqueNodeId, normalizeNodeId } from '../src/nodeId'

describe('node id', () => {
  it('preserves Chinese names and replaces only Windows-invalid path characters', () => {
    expect(normalizeNodeId(' 收盘决策_DeepSeek ')).toBe('收盘决策_DeepSeek')
    expect(normalizeNodeId('节点:一/二?')).toBe('节点_一_二_')
  })

  it('creates deterministic unique ids and can exclude the renamed node id', () => {
    expect(createUniqueNodeId('节点', ['节点', '节点1', '节点2'])).toBe('节点3')
    expect(createUniqueNodeId('节点', ['节点', '节点1'], '节点')).toBe('节点')
  })
})

describe('mobile node identity rename', () => {
  const oldNode: MobileNode = {
    id: 'Agent',
    name: '旧显示名',
    type_id: 'agent_node',
    graph_id: 'default',
  }
  const config: NodeInstanceConfig = {
    node_id: 'Agent',
    name: '旧显示名',
    type_id: 'agent_node',
    graph_id: 'default',
  }
  const graph: GraphConfig = {
    id: 'default',
    name: 'default',
    nodes: [
      {
        id: 'Agent',
        typeId: 'agent_node',
        name: '旧显示名',
        ui: { grid_x: 0, grid_y: 0 },
      },
      {
        id: 'Target',
        typeId: 'agent_node',
        name: 'Target',
        ui: { grid_x: 1, grid_y: 0 },
      },
    ],
    node_notes: { Agent: 'note' },
    output_routes: {
      Agent: [{ output_index: 0, targets: [{ node_id: 'Target', input_index: 0 }] }],
      Target: [{ output_index: 0, targets: [{ node_id: 'Agent', input_index: 0 }] }],
    },
  }

  it('moves the selected node, config, notes, and route references to the new Chinese id', () => {
    const result = renameMobileNodeIdentity({
      nodes: [oldNode],
      selectedNode: oldNode,
      nodeConfigs: { Agent: config },
      graphConfig: graph,
    }, 'Agent', '擒龙战法')

    expect(result.nodes[0]).toMatchObject({ id: '擒龙战法', name: '擒龙战法' })
    expect(result.selectedNode).toMatchObject({ id: '擒龙战法', name: '擒龙战法' })
    expect(result.nodeConfigs.Agent).toBeUndefined()
    expect(result.nodeConfigs['擒龙战法']).toMatchObject({ node_id: '擒龙战法', name: '擒龙战法' })
    expect(result.graphConfig?.nodes[0]).toMatchObject({ id: '擒龙战法', name: '擒龙战法' })
    expect(result.graphConfig?.node_notes).toEqual({ 擒龙战法: 'note' })
    expect(result.graphConfig?.output_routes['擒龙战法']?.[0]?.targets[0]?.node_id).toBe('Target')
    expect(result.graphConfig?.output_routes.Target?.[0]?.targets[0]?.node_id).toBe('擒龙战法')
  })

  it('aligns an inconsistent display name even when the node id does not change', () => {
    const result = renameMobileNodeIdentity({
      nodes: [oldNode],
      selectedNode: oldNode,
      nodeConfigs: { Agent: config },
      graphConfig: graph,
    }, 'Agent', 'Agent')

    expect(result.nodes[0]).toMatchObject({ id: 'Agent', name: 'Agent' })
    expect(result.selectedNode).toMatchObject({ id: 'Agent', name: 'Agent' })
    expect(result.nodeConfigs.Agent).toMatchObject({ node_id: 'Agent', name: 'Agent' })
    expect(result.graphConfig?.nodes[0]).toMatchObject({ id: 'Agent', name: 'Agent' })
  })
})
