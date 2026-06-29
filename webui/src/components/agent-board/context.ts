import type { InjectionKey, Ref } from 'vue'
import type {
  MessageEnvelope,
  NodeConfigChangeResponse,
  NodeInfo,
  GraphConfig,
  NodeInstanceConfig,
  NodeInstanceState,
  RuntimeEvent,
  RuntimeToolCall,
} from '../../api'

export type LinkEndpoint = {
  node: string
  index: number
}

export type LinkItem = {
  id: string
  from: LinkEndpoint
  to: LinkEndpoint
}

export type LinkSession = {
  from: LinkEndpoint
  pointerId: number
  startX: number
  startY: number
  currentX: number
  currentY: number
}

export type NodeCard = {
  id: string
  typeId: string
  name: string
  inputNum: number
  outputNum: number
  ui: { x: number; y: number }
  last_message: string | null
  lastRuntimeEvent?: RuntimeEvent | null
  runtimeEvents?: RuntimeEvent[]
  runtimeToolCalls?: RuntimeToolCall[]
  providerId?: string
  mode?: string
  webSearch?: 'enabled' | 'disabled'
  thinking?: 'enabled' | 'disabled'
  reasoningEffort?: string
  systemPrompt?: string
  plugins?: string[]
  tools?: string[]
  mcpServers?: string[]
  workingPath?: string
}

export type DragSession =
  | {
      itemId: string
      pointerId: number
      startPointerX: number
      startPointerY: number
      startX: number
      startY: number
      moved: boolean
    }
  | null

export type PanSession = {
  startPointerX: number
  startPointerY: number
  startScrollLeft: number
  startScrollTop: number
} | null

export type NodeRunState = {
  runId: string
  nodeId: string
  status: 'running' | 'finished' | 'stopped' | 'error'
  canceled: boolean
}

export type AgentBoardContext = {
  selectedNodeId: Ref<string | null>
  lastError: Ref<string | null>
  memoryMode: Ref<'agent' | 'file' | 'graph'>
  graphSnapshot: Ref<GraphConfig | null>
  graphLoadRequest: Ref<GraphConfig | null>
  currentGraphId: Ref<string | null>
  currentGraphName: Ref<string | null>

  availableNodes: Ref<NodeInfo[]>
  nodes: Ref<NodeCard[]>
  links: Ref<LinkItem[]>
  nodeConfigs: Ref<Record<string, NodeInstanceConfig>>

  boardRef: Ref<HTMLElement | null>
  canvasRef: Ref<HTMLElement | null>
  canvasScale: Ref<number>
  canvasWidth: Ref<number>
  canvasHeight: Ref<number>
  selectionRect: Ref<{ x: number; y: number; width: number; height: number } | null>
  suppressClickUntil: Ref<number>
  dragSession: Ref<DragSession>
  dragHoverTargetId: Ref<string | null>
  panSession: Ref<PanSession>
  linkSession: Ref<LinkSession | null>

  nodeStates: Ref<Record<string, NodeInstanceState>>
  nodeDonePulse: Ref<Record<string, number>>
  nodeRuns: Ref<Record<string, NodeRunState>>
  selectedNodeWorkingPath: Ref<string>
  selectedNodeWorkingPathRevision: Ref<number>

  selectNode: (id: string) => void
  openNodeSettings: (id: string) => void
  openNodeFolder: (id: string) => Promise<void>
  openGraphPanel: () => void
  triggerNode: (nodeId: string) => Promise<void>
  startClockNode: (nodeId: string) => Promise<void>
  createNodeFromPalette: (typeId: string, nodeName: string, fields?: Record<string, unknown>) => Promise<string | null>
  createNodeAtPosition: (
    typeId: string,
    nodeName: string,
    ui: { x: number; y: number },
    fields?: Record<string, unknown>,
  ) => Promise<string | null>
  previewMessage: (value: string | null) => string
  onNodePaletteDragStart: (node: NodeInfo, event: DragEvent) => void
  sendNodeMessage: (nodeId: string, message: string | MessageEnvelope) => Promise<void>
  renameNodeCard: (nodeId: string, nextName: string) => Promise<void>
  deleteNodeCard: (nodeId: string) => Promise<void>
  ensureNodeConfig: (nodeId: string) => Promise<void>
  refreshNodeConfig: (nodeId: string) => Promise<void>
  setNodeFields: (nodeId: string, fields: Record<string, unknown>) => Promise<NodeConfigChangeResponse | void>
  clearNodeFields: (nodeId: string, fields: string[]) => Promise<NodeConfigChangeResponse | void>

  isDragging: (id: string) => boolean
  isNodeSelected: (id: string) => boolean
  itemStyle: (id: string) => Record<string, string | number>
  onItemClick: (id: string, event: MouseEvent) => void
  onItemPointerDown: (id: string, event: PointerEvent) => void
  onItemPointerMove: (event: PointerEvent) => void
  endDrag: (event: PointerEvent) => void

  onBoardMouseDownCapture: (event: MouseEvent) => void
  onBoardWheel: (event: WheelEvent) => void
  onBoardDragOver: (event: DragEvent) => void
  onBoardDrop: (event: DragEvent) => void
  onNodeCardDragOver: (id: string, event: DragEvent) => void
  onNodeCardDrop: (id: string, event: DragEvent) => Promise<void>
  onWindowResize: () => void

  startLink: (id: string, outputIndex: number, event: PointerEvent) => void
  completeLink: (targetId: string, inputIndex: number, event: PointerEvent) => void
  linkPath: (link: LinkItem) => string
  activeLinkPath: () => string
  detachLinks: (id: string) => void

  linkFlows: Ref<{ id: string; linkId: string }[]>
  LINK_FLOW_DURATION_MS: number
  LINK_FLOW_BUBBLES: number[]

  isNodeRunning: (nodeId: string) => boolean
  isNodeWorking: (nodeId: string) => boolean
  isClockNode: (nodeId: string) => boolean
  isClockRunning: (nodeId: string) => boolean
  isNodeStopped: (nodeId: string) => boolean
  toggleNodeStop: (nodeId: string) => Promise<void>
  stopNodeWork: (nodeId: string) => Promise<void>
}

export const AgentBoardKey: InjectionKey<AgentBoardContext> = Symbol('AgentBoardContext')
