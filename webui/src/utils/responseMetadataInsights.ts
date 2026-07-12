type DataRecord = Record<string, any>

import { parseFilePatches, type ParsedFilePatch } from './responseMetadataDiff'
import { extractRuntimeToolInsights } from './responseMetadataRuntimeTools'

export type ResponseMetadataInsights = {
  available_tools?: DataRecord[]
  file_references?: DataRecord[]
  file_changes?: DataRecord[]
  commands?: DataRecord[]
  tool_activities?: DataRecord[]
}

export function extractResponseMetadataInsights(metadata: unknown): ResponseMetadataInsights {
  const root = record(metadata)
  const response = record(root.response)
  const items = responseItems(root, response)
  const outputsByCallId = indexCallOutputs(items)
  const runtimeCalls = records(root.runtime_tool_calls)
  const runtimeCallIds = new Set(runtimeCalls.map(callId).filter(Boolean))
  const availableTools = responseTools(response)
  const fileReferences: DataRecord[] = []
  const fileChanges: DataRecord[] = []
  const commands: DataRecord[] = []
  const toolActivities: DataRecord[] = []

  for (const item of items) {
    const itemType = text(item.type).toLowerCase()
    if (itemType === 'message') {
      fileReferences.push(...messageFileReferences(item))
      continue
    }
    if (itemType === 'file_search_call') {
      fileReferences.push(...fileSearchReferences(item))
      continue
    }
    if (itemType === 'apply_patch_call') {
      const change = fileChange(item, outputsByCallId)
      if (change) fileChanges.push(change)
      continue
    }
    if (itemType === 'shell_call' || itemType === 'local_shell_call') {
      const command = commandActivity(item, outputsByCallId)
      if (command) commands.push(command)
      continue
    }
    if (itemType === 'function_call') {
      if (runtimeCallIds.has(callId(item))) continue
      const name = text(item.name).toLowerCase()
      const args = jsonRecord(item.arguments)
      if (name === 'apply_patch') {
        fileChanges.push(...functionPatchChanges(item, args, outputsByCallId))
        continue
      }
      if (name === 'execute_console_command') {
        const command = functionCommandActivity(item, args, outputsByCallId)
        if (command) commands.push(command)
        continue
      }
    }
    if (itemType.endsWith('_call') && itemType !== 'web_search_call') {
      toolActivities.push(genericToolActivity(item, itemType, outputsByCallId))
    }
  }
  const runtimeInsights = extractRuntimeToolInsights(runtimeCalls)
  fileChanges.push(...runtimeInsights.fileChanges)
  commands.push(...runtimeInsights.commands)

  const insights: ResponseMetadataInsights = {}
  if (availableTools.length) insights.available_tools = availableTools
  const uniqueFiles = deduplicateFileReferences(fileReferences)
  if (uniqueFiles.length) insights.file_references = uniqueFiles
  if (fileChanges.length) insights.file_changes = fileChanges
  if (commands.length) insights.commands = commands
  if (toolActivities.length) insights.tool_activities = toolActivities
  return insights
}

function responseItems(root: DataRecord, response: DataRecord): DataRecord[] {
  const values = [...records(root.output_items), ...records(response.output)]
  const seen = new Set<string>()
  return values.filter((item) => {
    const key = text(item.id) || [item.type, item.call_id, item.name, item.arguments].map(text).join('\u0000')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function responseTools(response: DataRecord): DataRecord[] {
  return records(response.tools).map((tool) => {
    const toolType = text(tool.type) || 'tool'
    const name = text(tool.name)
      || text(tool.server_label)
      || toolType
    const output: DataRecord = {
      name,
      type: toolType,
    }
    if (text(tool.description)) output.description = text(tool.description)
    if (typeof tool.strict === 'boolean') output.strict = tool.strict

    const configuration: DataRecord = {}
    for (const [key, value] of Object.entries(tool)) {
      if (['name', 'type', 'description', 'strict'].includes(key)) continue
      if (value === undefined || value === null || value === '') continue
      configuration[key] = value
    }
    if (Object.keys(configuration).length) output.configuration = configuration
    return output
  })
}

function record(value: unknown): DataRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as DataRecord : {}
}

function records(value: unknown): DataRecord[] {
  return Array.isArray(value)
    ? value.filter((item): item is DataRecord => !!item && typeof item === 'object' && !Array.isArray(item))
    : []
}

function text(value: unknown): string {
  return String(value ?? '').trim()
}

function jsonRecord(value: unknown): DataRecord {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as DataRecord
  if (typeof value !== 'string' || !value.trim()) return {}
  try {
    return record(JSON.parse(value))
  } catch {
    return {}
  }
}

function callId(item: DataRecord): string {
  return text(item.call_id || item.id)
}

function indexCallOutputs(items: DataRecord[]): Map<string, DataRecord[]> {
  const indexed = new Map<string, DataRecord[]>()
  for (const item of items) {
    const itemType = text(item.type).toLowerCase()
    if (!itemType.endsWith('_call_output')) continue
    const id = callId(item)
    if (!id) continue
    const values = indexed.get(id) || []
    values.push(item)
    indexed.set(id, values)
  }
  return indexed
}

function messageFileReferences(item: DataRecord): DataRecord[] {
  const references: DataRecord[] = []
  for (const part of records(item.content)) {
    for (const annotation of records(part.annotations)) {
      const annotationType = text(annotation.type).toLowerCase()
      if (annotationType !== 'file_citation' && annotationType !== 'container_file_citation') continue
      const reference = fileIdentity(annotation)
      if (!reference) continue
      reference.source = annotationType
      for (const key of ['index', 'start_index', 'end_index']) {
        if (Number.isInteger(annotation[key])) reference[key] = annotation[key]
      }
      references.push(reference)
    }
  }
  return references
}

function fileSearchReferences(item: DataRecord): DataRecord[] {
  const queries = Array.isArray(item.queries) ? item.queries.map(text).filter(Boolean) : []
  const references: DataRecord[] = []
  for (const result of records(item.results)) {
    const reference = fileIdentity(result)
    if (!reference) continue
    reference.source = 'file_search'
    if (typeof result.score === 'number' && Number.isFinite(result.score)) reference.score = result.score
    if (text(result.text)) reference.text = text(result.text)
    if (record(result.attributes) && Object.keys(record(result.attributes)).length) reference.attributes = result.attributes
    if (queries.length) reference.queries = queries
    references.push(reference)
  }
  return references
}

function fileIdentity(value: DataRecord): DataRecord | null {
  const fileId = text(value.file_id)
  const filename = text(value.filename)
  const path = text(value.path)
  if (!fileId && !filename && !path) return null
  return {
    ...(fileId ? { file_id: fileId } : {}),
    ...(filename ? { filename } : {}),
    ...(path ? { path } : {}),
  }
}

function fileChange(item: DataRecord, outputsByCallId: Map<string, DataRecord[]>): DataRecord | null {
  const operation = record(item.operation)
  const operationType = text(operation.type).toLowerCase()
  const path = text(operation.path)
  if (!['create_file', 'update_file', 'delete_file'].includes(operationType) || !path) return null
  const id = callId(item)
  const change: DataRecord = {
    call_id: id,
    operation: operationType,
    path,
    status: text(item.status) || 'completed',
  }
  if (text(operation.diff)) change.diff = text(operation.diff)
  if (text(operation.diff)) change.patches = parseFilePatches(text(operation.diff), path, operationType)
  const outputs = outputsByCallId.get(id)
  if (outputs?.length) change.outputs = outputs
  return change
}

function functionPatchChanges(
  item: DataRecord,
  args: DataRecord,
  outputsByCallId: Map<string, DataRecord[]>,
): DataRecord[] {
  const patch = text(args.patch || args.diff || args.input)
  if (!patch) return []
  const id = callId(item)
  const outputs = outputsByCallId.get(id)
  return parseFilePatches(patch).map((parsed: ParsedFilePatch) => ({
    call_id: id,
    operation: parsed.operation,
    path: parsed.path,
    status: text(item.status) || 'completed',
    diff: parsed.rawPatch,
    patches: [parsed],
    ...(outputs?.length ? { outputs } : {}),
  }))
}

function commandActivity(item: DataRecord, outputsByCallId: Map<string, DataRecord[]>): DataRecord | null {
  const action = record(item.action)
  const command = action.command
  const commands = action.commands
  if (!text(command) && !Array.isArray(command) && !Array.isArray(commands)) return null
  const id = callId(item)
  const activity: DataRecord = {
    call_id: id,
    tool_type: text(item.type).replace(/_call$/, ''),
    status: text(item.status) || 'completed',
  }
  if (Array.isArray(command)) activity.command = command
  else if (text(command)) activity.command = text(command)
  else activity.commands = commands
  for (const key of ['working_directory', 'user']) {
    if (text(action[key])) activity[key] = text(action[key])
  }
  if (Number.isInteger(action.timeout_ms)) activity.timeout_ms = action.timeout_ms
  const outputs = outputsByCallId.get(id)
  if (outputs?.length) activity.outputs = outputs
  return activity
}

function functionCommandActivity(
  item: DataRecord,
  args: DataRecord,
  outputsByCallId: Map<string, DataRecord[]>,
): DataRecord | null {
  const command = args.command
  if (!text(command) && !Array.isArray(command)) return null
  const id = callId(item)
  const outputs = outputsByCallId.get(id)
  return {
    call_id: id,
    tool_type: text(item.name) || 'execute_console_command',
    status: text(item.status) || 'completed',
    command,
    ...(text(args.working_directory) ? { working_directory: text(args.working_directory) } : {}),
    ...(Number.isInteger(args.timeout_seconds) ? { timeout_seconds: args.timeout_seconds } : {}),
    ...(outputs?.length ? { outputs } : {}),
  }
}


function genericToolActivity(
  item: DataRecord,
  itemType: string,
  outputsByCallId: Map<string, DataRecord[]>,
): DataRecord {
  const id = callId(item)
  const activity: DataRecord = {
    call_id: id,
    tool_type: itemType.replace(/_call$/, ''),
    status: text(item.status) || 'completed',
  }
  for (const key of [
    'action', 'code', 'outputs', 'output', 'error', 'container_id',
    'pending_safety_checks', 'server_label', 'name', 'arguments', 'result',
  ]) {
    if (item[key] !== undefined && item[key] !== null && item[key] !== '') activity[key] = item[key]
  }
  if (activity.outputs === undefined) {
    const linkedOutputs = outputsByCallId.get(id)
    if (linkedOutputs?.length) activity.outputs = linkedOutputs
  }
  return activity
}

function deduplicateFileReferences(values: DataRecord[]): DataRecord[] {
  const seen = new Set<string>()
  return values.filter((value) => {
    const key = [value.source, value.file_id, value.filename, value.path, value.text].map(text).join('\u0000')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
