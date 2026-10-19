export type WorkspaceNodeTarget = { graphId: string; nodeId: string }

/** A node link identifies both its graph and node; partial links are errors. */
export function readWorkspaceNodeLink(href: string): WorkspaceNodeTarget | null {
  const params = new URL(href).searchParams
  if (!params.has('graph') && !params.has('node')) return null
  const graphId = params.get('graph'), nodeId = params.get('node')
  if (!graphId?.trim() || !nodeId?.trim()) throw new Error('节点链接不完整：需要同时指定画布和节点。')
  return { graphId, nodeId }
}
