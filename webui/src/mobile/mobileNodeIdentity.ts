import type { GraphConfig, MobileNode, NodeInstanceConfig } from '../api'

export type MobileNodeIdentityState = {
  nodes: MobileNode[]
  selectedNode: MobileNode | null
  nodeConfigs: Record<string, NodeInstanceConfig>
  graphConfig: GraphConfig | null
}

function renamedMobileNode(node: MobileNode, oldId: string, newId: string) {
  return node.id === oldId ? { ...node, id: newId, name: newId } : node
}

function renameGraphConfigIdentity(graph: GraphConfig | null, oldId: string, newId: string) {
  if (!graph) return null

  const nodeNotes = { ...(graph.node_notes || {}) }
  if (Object.prototype.hasOwnProperty.call(nodeNotes, oldId)) {
    const note = nodeNotes[oldId]
    if (note !== undefined) nodeNotes[newId] = note
    delete nodeNotes[oldId]
  }

  const outputRoutes = Object.fromEntries(
    Object.entries(graph.output_routes || {}).map(([sourceId, routes]) => [
      sourceId === oldId ? newId : sourceId,
      routes.map((route) => ({
        ...route,
        targets: route.targets.map((target) => (
          target.node_id === oldId ? { ...target, node_id: newId } : target
        )),
      })),
    ]),
  )

  return {
    ...graph,
    nodes: graph.nodes.map((node) => (
      node.id === oldId ? { ...node, id: newId, name: newId } : node
    )),
    node_notes: nodeNotes,
    output_routes: outputRoutes,
  }
}

export function renameMobileNodeIdentity(
  state: MobileNodeIdentityState,
  oldId: string,
  newId: string,
): MobileNodeIdentityState {
  if (oldId === newId) {
    return {
      nodes: state.nodes.map((node) => renamedMobileNode(node, oldId, newId)),
      selectedNode: state.selectedNode ? renamedMobileNode(state.selectedNode, oldId, newId) : null,
      nodeConfigs: Object.fromEntries(
        Object.entries(state.nodeConfigs).map(([nodeId, config]) => [
          nodeId,
          nodeId === oldId ? { ...config, node_id: newId, name: newId } : config,
        ]),
      ),
      graphConfig: renameGraphConfigIdentity(state.graphConfig, oldId, newId),
    }
  }

  const nodeConfigs = { ...state.nodeConfigs }
  const config = nodeConfigs[oldId]
  delete nodeConfigs[oldId]
  if (config) nodeConfigs[newId] = { ...config, node_id: newId, name: newId }

  return {
    nodes: state.nodes.map((node) => renamedMobileNode(node, oldId, newId)),
    selectedNode: state.selectedNode ? renamedMobileNode(state.selectedNode, oldId, newId) : null,
    nodeConfigs,
    graphConfig: renameGraphConfigIdentity(state.graphConfig, oldId, newId),
  }
}
