export type DiffLineKind = 'context' | 'removed' | 'added'

export type DiffSideLine = {
  lineNumber?: number
  kind: DiffLineKind
  text: string
}

export type DiffRow = {
  before?: DiffSideLine
  after?: DiffSideLine
}

export type DiffHunk = {
  header?: string
  rows: DiffRow[]
  hasLineNumbers: boolean
}

export type ParsedFilePatch = {
  operation: 'create_file' | 'update_file' | 'delete_file'
  path: string
  hunks: DiffHunk[]
  rawPatch: string
}

type PatchLine = {
  kind: DiffLineKind
  text: string
  oldLine?: number
  newLine?: number
}

const CONTEXT_LINES = 5

export function parseFilePatches(patch: string, fallbackPath = '', fallbackOperation = 'update_file'): ParsedFilePatch[] {
  const source = String(patch || '').replace(/\r\n/g, '\n')
  if (!source.trim()) return []
  if (source.includes('*** Begin Patch')) return parseCodexPatch(source)
  return parseUnifiedDiff(source, fallbackPath, normalizeOperation(fallbackOperation))
}

function parseCodexPatch(source: string): ParsedFilePatch[] {
  const lines = source.split('\n')
  const output: ParsedFilePatch[] = []
  let index = 0
  while (index < lines.length) {
    const currentLine = lines[index] ?? ''
    const match = /^\*\*\* (Add|Update|Delete) File:\s*(.+)$/.exec(currentLine)
    if (!match) {
      index += 1
      continue
    }
    const operation = normalizeOperation(`${String(match[1]).toLowerCase()}_file`)
    const path = String(match[2]).trim()
    const body: string[] = []
    index += 1
    while (index < lines.length && !/^\*\*\* (Add|Update|Delete) File:/.test(lines[index] ?? '') && lines[index] !== '*** End Patch') {
      body.push(lines[index] ?? '')
      index += 1
    }
    output.push({
      operation,
      path,
      hunks: parsePatchBody(body, operation),
      rawPatch: body.join('\n'),
    })
  }
  return output
}

function parseUnifiedDiff(
  source: string,
  fallbackPath: string,
  fallbackOperation: ParsedFilePatch['operation'],
): ParsedFilePatch[] {
  const lines = source.split('\n')
  const output: ParsedFilePatch[] = []
  let index = 0
  while (index < lines.length) {
    let path = fallbackPath
    let operation = fallbackOperation
    const start = index
    if ((lines[index] ?? '').startsWith('diff --git ')) index += 1
    if (lines[index]?.startsWith('--- ')) {
      const oldPath = cleanDiffPath((lines[index] ?? '').slice(4))
      const nextLine = lines[index + 1] ?? ''
      const newPath = nextLine.startsWith('+++ ') ? cleanDiffPath(nextLine.slice(4)) : ''
      path = newPath && newPath !== '/dev/null' ? newPath : oldPath
      if (oldPath === '/dev/null') operation = 'create_file'
      if (newPath === '/dev/null') operation = 'delete_file'
      index += newPath ? 2 : 1
    }
    const body: string[] = []
    while (index < lines.length && !(lines[index] ?? '').startsWith('diff --git ') && !(body.length && (lines[index] ?? '').startsWith('--- '))) {
      body.push(lines[index] ?? '')
      index += 1
    }
    if (path || body.some((line) => line.startsWith('@@'))) {
      output.push({ operation, path: path || 'Unknown file', hunks: parsePatchBody(body, operation), rawPatch: lines.slice(start, index).join('\n') })
    } else if (index === start) {
      index += 1
    }
  }
  return output
}

function parsePatchBody(lines: string[], operation: ParsedFilePatch['operation']): DiffHunk[] {
  const hunks: DiffHunk[] = []
  let header = ''
  let oldLine: number | undefined
  let newLine: number | undefined
  let values: PatchLine[] = []

  const flush = () => {
    if (!values.length) return
    for (const group of changedGroups(values)) {
      const selected = values.slice(Math.max(0, group.start - CONTEXT_LINES), Math.min(values.length, group.end + CONTEXT_LINES + 1))
      hunks.push({ header: header || undefined, rows: alignRows(selected), hasLineNumbers: selected.some((line) => line.oldLine !== undefined || line.newLine !== undefined) })
    }
    values = []
  }

  for (const line of lines) {
    const hunkMatch = /^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@(.*)$/.exec(line)
    if (hunkMatch) {
      flush()
      oldLine = Number(hunkMatch[1])
      newLine = Number(hunkMatch[2])
      header = line
      continue
    }
    if (line.startsWith('@@')) {
      flush()
      oldLine = undefined
      newLine = undefined
      header = line
      continue
    }
    if (line.startsWith('*** Move to:')) continue
    if (line.startsWith('\\ No newline at end of file')) continue
    const prefix = line[0]
    if (prefix === '+') {
      values.push({ kind: 'added', text: line.slice(1), newLine })
      if (newLine !== undefined) newLine += 1
    } else if (prefix === '-') {
      values.push({ kind: 'removed', text: line.slice(1), oldLine })
      if (oldLine !== undefined) oldLine += 1
    } else if (prefix === ' ' || (operation === 'update_file' && line !== '')) {
      const value = prefix === ' ' ? line.slice(1) : line
      values.push({ kind: 'context', text: value, oldLine, newLine })
      if (oldLine !== undefined) oldLine += 1
      if (newLine !== undefined) newLine += 1
    } else if (operation === 'create_file' && line !== '') {
      values.push({ kind: 'added', text: line, newLine })
      if (newLine !== undefined) newLine += 1
    }
  }
  flush()
  return hunks
}

function changedGroups(lines: PatchLine[]): Array<{ start: number; end: number }> {
  const groups: Array<{ start: number; end: number }> = []
  for (let index = 0; index < lines.length; index += 1) {
    if (lines[index]?.kind === 'context') continue
    const last = groups[groups.length - 1]
    if (last && index - last.end <= CONTEXT_LINES * 2 + 1) last.end = index
    else groups.push({ start: index, end: index })
  }
  return groups.length ? groups : [{ start: 0, end: Math.max(0, lines.length - 1) }]
}

function alignRows(lines: PatchLine[]): DiffRow[] {
  const rows: DiffRow[] = []
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    if (!line) break
    if (line.kind === 'context') {
      rows.push({
        before: { kind: 'context', text: line.text, lineNumber: line.oldLine },
        after: { kind: 'context', text: line.text, lineNumber: line.newLine },
      })
      index += 1
      continue
    }
    const removed: PatchLine[] = []
    const added: PatchLine[] = []
    while (index < lines.length && lines[index]?.kind !== 'context') {
      const changedLine = lines[index]
      if (!changedLine) break
      if (changedLine.kind === 'removed') removed.push(changedLine)
      else added.push(changedLine)
      index += 1
    }
    const count = Math.max(removed.length, added.length)
    for (let offset = 0; offset < count; offset += 1) {
      const before = removed[offset]
      const after = added[offset]
      rows.push({
        ...(before ? { before: { kind: 'removed' as const, text: before.text, lineNumber: before.oldLine } } : {}),
        ...(after ? { after: { kind: 'added' as const, text: after.text, lineNumber: after.newLine } } : {}),
      })
    }
  }
  return rows
}

function cleanDiffPath(value: string): string {
  return value.trim().replace(/^[ab]\//, '').split('\t')[0] ?? ''
}

function normalizeOperation(value: string): ParsedFilePatch['operation'] {
  if (value === 'create_file' || value === 'add_file') return 'create_file'
  if (value === 'delete_file') return 'delete_file'
  return 'update_file'
}
