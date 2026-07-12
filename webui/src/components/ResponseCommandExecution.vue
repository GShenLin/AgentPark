<script setup lang="ts">
type DataRecord = Record<string, any>

const props = defineProps<{ command: DataRecord }>()

function text(value: unknown): string {
  return String(value ?? '')
}

function commandText(): string {
  const value = props.command.command
  if (Array.isArray(value)) return value.map(text).join(' ')
  if (text(value).trim()) return text(value)
  const values = Array.isArray(props.command.commands) ? props.command.commands : []
  return values.map((item: unknown) => {
    if (!item || typeof item !== 'object') return text(item)
    const command = (item as DataRecord).command
    return Array.isArray(command) ? command.map(text).join(' ') : text(command)
  }).filter(Boolean).join('\n')
}

function outputRecords(): DataRecord[] {
  return Array.isArray(props.command.outputs)
    ? props.command.outputs.filter((item: unknown): item is DataRecord => !!item && typeof item === 'object')
    : []
}

function parsedOutput(item: DataRecord): DataRecord {
  const raw = item.output ?? item.result ?? item.content
  if (raw && typeof raw === 'object') return raw as DataRecord
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object') return parsed as DataRecord
    } catch {
      return { stdout: raw }
    }
  }
  return item
}
</script>

<template>
  <div class="command-execution">
    <div class="command-label">Command</div>
    <pre class="command-code">{{ commandText() }}</pre>
    <div class="command-meta">
      <span v-if="command.working_directory">Working directory: {{ command.working_directory }}</span>
      <span v-if="command.timeout_seconds">Timeout: {{ command.timeout_seconds }}s</span>
      <span v-else-if="command.timeout_ms">Timeout: {{ command.timeout_ms }}ms</span>
    </div>
    <div v-for="(item, index) in outputRecords()" :key="index" class="execution-result">
      <div class="result-meta">
        <span v-if="parsedOutput(item).returncode !== undefined">Exit code: {{ parsedOutput(item).returncode }}</span>
        <span v-if="parsedOutput(item).status">{{ parsedOutput(item).status }}</span>
        <span v-if="parsedOutput(item).duration_ms !== undefined">{{ parsedOutput(item).duration_ms }}ms</span>
      </div>
      <template v-if="parsedOutput(item).stdout !== undefined">
        <div class="stream-label">stdout</div>
        <pre class="stream stdout">{{ text(parsedOutput(item).stdout) || '(empty)' }}</pre>
      </template>
      <template v-if="parsedOutput(item).stderr !== undefined">
        <div class="stream-label stderr-label">stderr</div>
        <pre class="stream stderr">{{ text(parsedOutput(item).stderr) || '(empty)' }}</pre>
      </template>
      <pre v-if="parsedOutput(item).stdout === undefined && parsedOutput(item).stderr === undefined" class="stream">{{ JSON.stringify(parsedOutput(item), null, 2) }}</pre>
    </div>
    <div v-if="!outputRecords().length" class="no-output">No command output was included in this provider response.</div>
  </div>
</template>

<style scoped>
.command-execution {
  min-width: 0;
}

.command-label,
.stream-label {
  margin-top: 6px;
  color: rgba(125, 211, 252, 0.88);
  font-size: 10px;
  font-weight: 700;
}

.command-code,
.stream {
  max-height: 280px;
  margin: 4px 0 0;
  padding: 7px;
  overflow: auto;
  border-radius: 6px;
  background: rgba(2, 6, 23, 0.5);
  color: rgba(203, 213, 225, 0.92);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 10px;
}

.command-meta,
.result-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
  color: rgba(148, 163, 184, 0.88);
  font-size: 10px;
}

.execution-result {
  margin-top: 7px;
  padding-top: 1px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}

.stderr-label {
  color: rgba(252, 165, 165, 0.9);
}

.stderr {
  color: rgba(254, 202, 202, 0.92);
}

.no-output {
  margin-top: 6px;
  color: rgba(148, 163, 184, 0.8);
  font-size: 10px;
  font-style: italic;
}
</style>
