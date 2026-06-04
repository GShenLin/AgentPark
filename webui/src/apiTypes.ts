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
  systemPrompt?: string
  tools?: string[]
  workingPath?: string
}

export type GraphConfig = {
  id: string
  name: string
  nodes: GraphNode[]
  links: GraphLink[]
  source_graph_id?: string
}

export type GraphInfo = {
  id: string
  name: string
  updated_at?: string
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
  diagnostics?: string[]
}

export type RuntimeEvent = RuntimeNoticeEvent | ToolRuntimeEvent

export type RuntimeToolCall = {
  call_id: string
  name?: string
  provider?: string | null
  arguments?: Record<string, unknown> | null
  status: string
  duration_ms?: number | null
  error?: string | null
  result_preview?: string | null
  diagnostics?: string[] | null
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
  ui?: {
    x?: number
    y?: number
  }
  state?: NodeInstanceState
  pending_count?: number
  schema?: Record<string, any>
  [key: string]: any
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
  | { type: 'tool_call'; name?: string; args?: unknown }
  | { type: 'meta'; meta?: Record<string, unknown> }

export type MessageEnvelope = {
  id?: string
  role?: string
  parts: MessagePart[]
  created_at?: string
  trace_id?: string
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
  last_message?: string
  last_run_at?: string
  last_runtime_event?: RuntimeEvent | null
  runtime_tool_calls?: RuntimeToolCall[]
  input_num?: number
  output_num?: number
}

export type MobileNodeConversation = {
  memory_path: string | null
  messages_path?: string | null
  text: string
  messages: MessageEnvelope[]
  state?: NodeInstanceState
  last_message?: string
}
