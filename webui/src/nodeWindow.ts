import { getActiveApiBase, requestApiJson } from './api'

export type NodeWindowTarget = { graphId: string; nodeId: string; requestId?: string }
export type NodeWindowResizeEdge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'
export interface NodeWindowBridge {
  readonly target: NodeWindowTarget
  ready(): void
  fail(message: string): void
  setMode(mode: 'card' | 'conversation', width: number, height: number, noteHeight?: number): Promise<void>
  retarget(nodeId: string): Promise<void>
  beginDrag(): void
  moveDrag(): void
  endDrag(): void
  beginResize(edge: NodeWindowResizeEdge): void
  moveResize(): void
  endResize(): void
  minimize(): void
  openInBrowser(): Promise<void>
  copyText(text: string): Promise<void>
  close(): void
}
declare global { interface Window { agentParkNodeWindow?: NodeWindowBridge } }

export async function openNodeWindow(nodeId: string, graphId: string): Promise<void> {
  const result = await requestApiJson(getActiveApiBase(),
    `/api/nodes/instances/${encodeURIComponent(nodeId)}/open-window?graph_id=${encodeURIComponent(graphId)}`,
    { method: 'POST' })
  if (result.ok !== true) throw new Error('节点窗口未确认就绪。')
}
