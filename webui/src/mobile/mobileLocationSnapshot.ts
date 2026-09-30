import { getMobileNodeConversation, listGraphProfiles, listMobileGraphs, listMobileNodes, listMobilePcs } from '../api'

/** Load a destination without visiting or mutating any intermediate page. */
export async function loadMobileLocationSnapshot(pcId: string, graphId?: string, nodeId?: string, isCurrent = () => true) {
  function check() { if (!isCurrent()) throw new DOMException('Location restoration cancelled.', 'AbortError') }
  if (nodeId && !graphId) throw new Error('无法恢复访问位置：节点缺少 Graph ID。')
  const [pcs, graphs] = await Promise.all([listMobilePcs(), listMobileGraphs(pcId)])
  check()
  const pc = pcs.find(item => item.id === pcId)
  if (!pc) throw new Error(`无法恢复访问位置：设备已不存在或不可访问：${pcId}`)
  const graph = graphId ? graphs.flatMap(item => item.graphs).find(item => item.id === graphId) : null
  if (graphId && !graph) throw new Error(`无法恢复访问位置：Graph 已不存在或不可访问：${graphId}`)
  const nodes = graph ? await listMobileNodes(pcId, graph.id) : []
  check()
  const node = nodeId ? nodes.find(item => item.id === nodeId) : null
  if (nodeId && !node) throw new Error(`无法恢复访问位置：节点已不存在或不可访问：${nodeId}`)
  const conversation = node && graph ? await getMobileNodeConversation(pcId, graph.id, node.id, 'conversation') : null
  const profiles = graph ? null : await listGraphProfiles()
  check()
  return { pcs, pc, graphs, graph: graph || null, nodes, node: node || null, conversation, profiles }
}
