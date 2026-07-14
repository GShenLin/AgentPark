
export type RemoteEndpoint = {
  id: string
  name: string
  host: string
  port: number
  private?: boolean
}

export type RemoteStatus = {
  is_local_client: boolean
}

export type RunInfo = {
  task_id: number
  pid: number | null
  task: string | null
  memory_path: string | null
  status: 'running' | 'finished'
  started_at: string | null
  finished_at: string | null
  exitcode: number | null
}

export type ProviderInfo = {
  id: string
  supportmode: string[]
  features?: Record<string, {
    supported?: boolean
    values?: string[]
    requires?: string
    transport?: string
  }>
}

export type NodeInfo = {
  id: string
  name: string
  description?: string
  input_num?: number
  output_num?: number
  accepts?: string[]
  produces?: string[]
}

export type NodeTemplate = {
  type_id: string
  name: string
  description?: string
  input_num?: number
  output_num?: number
  accepts?: string[]
  produces?: string[]
  schema?: Record<string, any>
  fields?: Record<string, any>
}

export type PasteAgentConfig = {
  agent_id: string
  name?: string
  provider_id: string
  mode?: string
  web_search?: 'enabled' | 'disabled'
  thinking?: 'enabled' | 'disabled'
  reasoning_effort?: string
  system_prompt?: string
  tools?: string[]
}

export type GraphLinkEndpoint = {
  node: string
  index: number
}

export type GraphLink = {
  id: string
  from: GraphLinkEndpoint
  to: GraphLinkEndpoint
}

export type GraphOutputRouteTarget = {
  node_id: string
  input_index: number
}

export type GraphOutputRoute = {
  output_index: number
  targets: GraphOutputRouteTarget[]
}

export type GraphOutputRoutes = Record<string, GraphOutputRoute[]>

export type GraphNode = {
  id: string
  typeId: string
  name: string
  ui: {
    x: number
    y: number
  }
  input_num?: number
  output_num?: number
  providerId?: string
  mode?: string
  web_search?: 'enabled' | 'disabled'
  thinking?: 'enabled' | 'disabled'
  reasoning_effort?: string
  instruction?: string
  systemPrompt?: string
  plugins?: string[]
  tools?: string[]
  mcpServers?: string[]
  workingPath?: string
}

export type GraphConfig = {
  id: string
  name: string
  working_path?: string
  nodes: GraphNode[]
  output_routes: GraphOutputRoutes
  source_graph_id?: string
  version?: number
  unchanged?: boolean
  private?: boolean
}

export type GraphInfo = {
  id: string
  name: string
  updated_at?: string
  readonly?: boolean
  deletable?: boolean
  editable?: boolean
  private?: boolean
  visibility_editable?: boolean
}

export type AgentProfile = {
  id: string
  name: string
  node_type_id: string
  source_graph_id?: string
  source_node_id?: string
  node_name?: string
  fields: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export type AgentProfileListResponse = {
  version: number
  profiles: AgentProfile[]
}

export type GraphProfileNodeConfig = {
  node_id: string
  graph_id: string
  type_id: string
  name?: string
  fields: Record<string, unknown>
  ui?: {
    x?: number
    y?: number
    width?: number
    height?: number
  }
  input_num?: number
  output_num?: number
}

export type GraphProfile = {
  id: string
  name: string
  source_graph_id?: string
  graph: GraphConfig
  node_configs: GraphProfileNodeConfig[]
  created_at?: string
  updated_at?: string
}

export type GraphProfileListResponse = {
  version: number
  profiles: GraphProfile[]
}

export type NodeRunStatus = 'running' | 'finished' | 'stopped' | 'error'

export type NodeInstanceState = 'idle' | 'working' | 'stop'

export type RuntimeNoticeEvent = {
  type: 'runtime_notice'
  message: string
  source?: string
  stage?: string
  name?: string
  call_id?: string | null
  provider?: string | null
}

export type ToolRuntimeEvent = {
  type: 'tool_call_start' | 'tool_call_end'
  name?: string
  call_id?: string | null
  provider?: string | null
  arguments?: Record<string, unknown>
  status?: string
  duration_ms?: number
  error?: string
  result_preview?: string
  result_chars?: number
  result_preview_truncated?: boolean
  diagnostics?: string[]
}

export type ServerToolActivityEvent = {
  type: 'server_tool_activity'
  call_id: string
  tool_type: string
  status: string
  provider?: string | null
  action?: Record<string, unknown>
  sources?: Array<{ url: string; title?: string; type?: string }>
  details?: Record<string, unknown>
  error?: string
}

export type RuntimeEvent = RuntimeNoticeEvent | ToolRuntimeEvent | ServerToolActivityEvent

export type UserInteractionOption = {
  value: string
  label: string
  disabled?: boolean
}

export type UserInteractionField = {
  id: string
  type: 'text' | 'textarea' | 'select' | 'multiselect' | 'checkbox' | 'file' | 'custom_html'
  label: string
  description?: string
  placeholder?: string
  required?: boolean
  default?: unknown
  options?: UserInteractionOption[]
  accept?: string
  multiple?: boolean
  html?: string
  css?: string
  js?: string
  height?: number
  initial_data?: Record<string, unknown>
}

export type UserInteractionRequest = {
  id: string
  status: 'pending' | 'submitted' | 'cancelled' | 'expired'
  created_at?: string
  updated_at?: string
  expires_at?: number
  timeout_sec?: number
  schema: {
    title: string
    description?: string
    confirm_label?: string
    fields: UserInteractionField[]
  }
  agent?: {
    graph_id?: string
    node_id?: string
    node_name?: string
  }
  response?: Record<string, unknown> | null
}

export type RuntimeToolCall = {
  call_id: string
  name?: string
  provider?: string | null
  arguments?: Record<string, unknown> | null
  status: string
  duration_ms?: number | null
  error?: string | null
  result_preview?: string | null
  result_chars?: number | null
  result_preview_truncated?: boolean | null
  diagnostics?: string[] | null
}

export type ProviderRequestSummary = {
  request_index?: number
  request_api?: string
  continuation_mode?: string
  responses_mode?: string
  requested_responses_mode?: string
  previous_response_id_present?: boolean
  input_item_count?: number
  approx_input_chars?: number
  approx_input_tokens?: number
  environment_context_chars?: number
  largest_input_items?: Record<string, unknown>[]
  tool_call_chars_by_call?: Record<string, unknown>[]
  tool_call_chars_total?: number
  tool_result_chars_by_call?: Record<string, unknown>[]
  tool_result_chars_total?: number
  largest_tool_result?: Record<string, unknown>
  tools_included?: string[]
  tools_included_count?: number
  stream?: boolean
  usage?: ProviderRequestUsage | null
}

export type ProviderRequestUsage = {
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  cached_input_tokens?: number
  cache_write_input_tokens?: number
  reasoning_output_tokens?: number
}

export type ProviderRequestTotals = {
  request_count?: number
  approx_input_chars?: number
  approx_input_tokens?: number
  tool_call_chars?: number
  tool_result_chars?: number
  last_request_index?: number
  completed_request_count?: number
  last_completed_request_index?: number
  actual_input_tokens?: number
  actual_output_tokens?: number
  actual_total_tokens?: number
  actual_cached_input_tokens?: number
  actual_cache_write_input_tokens?: number
  actual_reasoning_output_tokens?: number
}

export type NodeInstanceConfig = {
  node_id: string
  type_id: string
  name?: string
  graph_id?: string
  last_message?: string
  last_runtime_event?: RuntimeEvent | null
  runtime_events?: RuntimeEvent[]
  runtime_tool_calls?: RuntimeToolCall[]
  provider_request_summaries?: ProviderRequestSummary[]
  provider_request_totals?: ProviderRequestTotals | null
  ui?: {
    x?: number
    y?: number
  }
  state?: NodeInstanceState
  pending_count?: number
  inflight?: Record<string, unknown> | null
  _stop_requested?: boolean
  schema?: Record<string, any>
  [key: string]: any
}

export type NodeInstanceConfigListResponse = {
  nodes: NodeInstanceConfig[]
  node_ids?: string[]
  version?: number
  partial?: boolean
}

export type NodeConfigChangeResponse = {
  ok: boolean
  config_path: string
  before: Record<string, unknown>
  after: Record<string, unknown>
  changed_fields: string[]
  effective: string
  warnings: string[]
}

export type ResourceKind = 'image' | 'video' | 'audio' | 'doc' | 'file' | 'url'

export type MessagePart =
  | { type: 'text'; text: string }
  | {
      type: 'resource'
      resource: {
        id?: string
        uri: string
        kind?: ResourceKind | string
        mime?: string
        name?: string
        source?: string
        metadata?: Record<string, unknown>
      }
    }
  | { type: 'structured'; data: unknown }
  | {
      type: 'tool_call'
      call_id?: string
      name?: string
      provider?: string
      status?: string
      duration_ms?: number
      error?: string
      result_preview?: string
      result_chars?: number
      result_preview_truncated?: boolean
      diagnostics?: string[]
      args?: unknown
      sources?: Array<{ url: string; title?: string; type?: string }>
      details?: Record<string, unknown>
    }
  | { type: 'meta'; meta?: Record<string, unknown> }

export type MessageEnvelope = {
  id?: string
  role?: string
  parts: MessagePart[]
  created_at?: string
  trace_id?: string
}

export type MemoryHistoryMode =
  | 'recent'
  | 'all'
  | 'latest_turn'
  | 'latest_turn_progress'
  | 'latest_turn_metadata'

export type LatestTurnProgressSummary = {
  item_count: number
  tool_count: number
}

export type PendingNodeInput = {
  payload: string | MessageEnvelope
  depth: number
  visited: string[]
  link_id?: string
  from_output_index?: number
  to_input_index?: number
}

export type FileItem = {
  name: string
  path: string
  type: 'dir' | 'file'
}

export type FileListResponse = {
  files: FileItem[]
  current_path: string
}

export type MobilePcInstance = {
  id: string
  name: string
  path: string
}

export type MobilePc = {
  id: string
  name: string
  instance_count: number
  instances: MobilePcInstance[]
}

export type MobileGraph = {
  id: string
  name: string
  display_name: string
  instance_id: string
  instance_name: string
  instance_path: string
  updated_at?: string | null
  readonly?: boolean
  deletable?: boolean
  editable?: boolean
}

export type MobileGraphInstance = MobilePcInstance & {
  graphs: MobileGraph[]
}

export type MobileNode = {
  id: string
  name: string
  type_id: string
  graph_id: string
  state?: NodeInstanceState
  pending_count?: number
  has_inflight?: boolean
  stop_requested?: boolean
  last_message?: string
  last_run_at?: string
  last_runtime_event?: RuntimeEvent | null
  runtime_tool_calls?: RuntimeToolCall[]
  goal?: string
  goal_state?: Record<string, unknown> | null
  input_num?: number
  output_num?: number
  readonly?: boolean
}

export type NodeDesktopViewPosition = {
  display_id?: string
  x: number
  y: number
}

export type NodeDesktopViewPanelSize = {
  width: number
  height: number
}

export type NodeDesktopViewLive = {
  text?: string
  trace_id?: string
  updated_at?: number
  is_streaming?: boolean
  version?: number
  event_type?: string
  event?: Record<string, unknown>
  interactive_session_id?: string
}

export type NodeDesktopView = {
  view_id: string
  graph_id: string
  node_id: string
  visible: boolean
  pinned: boolean
  position?: NodeDesktopViewPosition
  panel_size?: NodeDesktopViewPanelSize
  avatar_style?: string
  created_at?: string
  updated_at?: string
  last_invoked_at?: string
  node: MobileNode & {
    working_path?: string
  }
  live?: NodeDesktopViewLive
}

export type NodeDesktopViewListResponse = {
  schema_version: number
  views: NodeDesktopView[]
}

export type PetAvatarSequenceFrame = {
  src: string
  url?: string
  holdFrames: number
}

export type PetAvatarTransformKeyframe = {
  frame: number
  x: number
  y: number
  rotation: number
  scaleX: number
  scaleY: number
}

export type PetAvatarColorKeyframe = {
  frame: number
  color: string
  opacity: number
}

export type PetAvatarAnimationTracks = {
  transform?: PetAvatarTransformKeyframe[]
  color?: PetAvatarColorKeyframe[]
}

export type PetAvatarGifState = {
  type: 'gif'
  src: string
  url?: string
  loop: boolean
}

export type PetAvatarSequenceState = {
  type: 'sequence'
  loop: boolean
  frames: PetAvatarSequenceFrame[]
  tracks?: PetAvatarAnimationTracks
}

export type PetAvatarState = PetAvatarGifState | PetAvatarSequenceState

export type PetAvatarFrame = {
  version: 1
  id: string
  name: string
  renderer: 'sprite2d'
  fps: number
  states: Record<string, PetAvatarState>
  created_at?: string
  updated_at?: string
}

export type PetAvatarSummary = {
  id: string
  name: string
  renderer: 'sprite2d'
  fps: number
  states: string[]
  path: string
  valid: boolean
  asset_validation?: 'deferred'
  error?: string
}

export type MobileNodeConversation = {
  memory_path: string | null
  messages_path?: string | null
  text: string
  messages: MessageEnvelope[]
  history_complete?: boolean
  latest_turn_progress_loaded?: boolean
  latest_turn_metadata_loaded?: boolean
  latest_turn_progress_summary?: LatestTurnProgressSummary
  state?: NodeInstanceState
  last_message?: string
  live_message?: string
  thinking_message?: string
  activity_message?: string
}
