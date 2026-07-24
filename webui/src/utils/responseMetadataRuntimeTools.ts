import { parseFilePatches, type ParsedFilePatch } from './responseMetadataDiff'

type DataRecord = Record<string, any>

export function extractRuntimeToolInsights(runtimeCalls: DataRecord[]): {
  fileChanges: DataRecord[]
  commands: DataRecord[]
} {
  const fileChanges: DataRecord[] = []
  const commands: DataRecord[] = []
  for (const call of runtimeCalls) {
    const name = text(call.name).toLowerCase()
    const args = record(call.arguments)
    const result = jsonRecord(call.result)
    if (name === 'apply_patch') {
      const changes = runtimeFileChanges(call, result)
      fileChanges.push(...(changes.length ? changes : patchArgumentChanges(call, args)))
    } else if (name === 'execute_console_command') {
      const command = runtimeCommandActivity(call, args, result)
      if (command) commands.push(command)
    } else if (name === 'workspace_exec') {
      commands.push(...runtimeWorkspaceCommands(call, args, result))
    }
  }
  return { fileChanges, commands }
}

function runtimeFileChanges(call: DataRecord, result: DataRecord): DataRecord[] {
  return records(result.file_changes).filter((change) => records(change.hunks).length > 0).map((change) => {
    const operation = text(change.operation)
    const path = text(change.path)
    const parsedOperation = operation === 'add' ? 'create_file' : operation === 'delete' ? 'delete_file' : 'update_file'
    const patch: ParsedFilePatch = {
      operation: parsedOperation,
      path,
      rawPatch: '',
      hunks: records(change.hunks).map((hunk) => ({
        hasLineNumbers: true,
        header: hunk.before_start || hunk.after_start
          ? `−${text(hunk.before_start) || '0'} +${text(hunk.after_start) || '0'}`
          : undefined,
        rows: records(hunk.rows).map((row) => ({
          ...(row.before_text !== undefined ? {
            before: {
              kind: text(row.kind) === 'context' ? 'context' as const : 'removed' as const,
              lineNumber: Number.isInteger(row.before_line) ? row.before_line : undefined,
              text: String(row.before_text),
            },
          } : {}),
          ...(row.after_text !== undefined ? {
            after: {
              kind: text(row.kind) === 'context' ? 'context' as const : 'added' as const,
              lineNumber: Number.isInteger(row.after_line) ? row.after_line : undefined,
              text: String(row.after_text),
            },
          } : {}),
        })),
      })),
    }
    return {
      call_id: callId(call),
      operation: parsedOperation,
      path,
      status: text(call.status) || text(result.status) || 'completed',
      patches: [patch],
    }
  }).filter((change) => text(change.path))
}

function patchArgumentChanges(call: DataRecord, args: DataRecord): DataRecord[] {
  const patch = text(args.patch || args.diff || args.input)
  if (!patch) return []
  return parseFilePatches(patch).map((parsed) => ({
    call_id: callId(call),
    operation: parsed.operation,
    path: parsed.path,
    status: text(call.status) || 'completed',
    diff: parsed.rawPatch,
    patches: [parsed],
  }))
}

function runtimeCommandActivity(call: DataRecord, args: DataRecord, result: DataRecord): DataRecord | null {
  const command = args.command ?? result.command
  if (!text(command) && !Array.isArray(command)) return null
  return {
    call_id: callId(call),
    tool_type: text(call.name) || 'execute_console_command',
    status: text(call.status) || text(result.status) || 'completed',
    command,
    ...(text(result.cwd) ? { working_directory: text(result.cwd) } : {}),
    ...(Number.isInteger(args.timeout_seconds) ? { timeout_seconds: args.timeout_seconds } : {}),
    outputs: [{ type: 'runtime_tool_call_output', output: result }],
  }
}

function runtimeWorkspaceCommands(
  call: DataRecord,
  args: DataRecord,
  result: DataRecord,
): DataRecord[] {
  const declaredOperations = new Map<string, DataRecord>()
  for (const stage of records(args.stages)) {
    for (const operation of records(stage.operations)) {
      declaredOperations.set(text(operation.id), operation)
    }
  }
  const commands: DataRecord[] = []
  for (const stageResult of records(result.stages)) {
    for (const operationResult of records(stageResult.operations)) {
      if (text(operationResult.kind) !== 'run_command') continue
      const operationId = text(operationResult.id)
      const declaration = declaredOperations.get(operationId) ?? {}
      const nestedCall: DataRecord = {
        call_id: `${callId(call)}:${operationId}`,
        name: 'execute_console_command',
        status: text(operationResult.status) || text(call.status),
      }
      const command = runtimeCommandActivity(
        nestedCall,
        record(declaration.arguments),
        record(operationResult.result),
      )
      if (command) commands.push(command)
    }
  }
  return commands
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

function callId(item: DataRecord): string {
  return text(item.call_id || item.id)
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
