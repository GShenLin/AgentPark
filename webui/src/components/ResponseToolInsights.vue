<script setup lang="ts">
import { computed } from 'vue'
import { extractResponseMetadataInsights } from '../utils/responseMetadataInsights'
import type { ParsedFilePatch } from '../utils/responseMetadataDiff'
import ResponseCommandExecution from './ResponseCommandExecution.vue'
import ResponseFileDiff from './ResponseFileDiff.vue'

const props = defineProps<{ metadata: unknown }>()

type DataRecord = Record<string, any>

const data = computed<DataRecord>(() => extractResponseMetadataInsights(props.metadata))

const availableTools = computed<DataRecord[]>(() => records(data.value.available_tools))
const fileReferences = computed<DataRecord[]>(() => records(data.value.file_references))
const fileChanges = computed<DataRecord[]>(() => records(data.value.file_changes))
const commands = computed<DataRecord[]>(() => records(data.value.commands))
const toolActivities = computed<DataRecord[]>(() => records(data.value.tool_activities))
const hasInsights = computed(() => (
  availableTools.value.length > 0
  || fileReferences.value.length > 0
  || fileChanges.value.length > 0
  || commands.value.length > 0
  || toolActivities.value.length > 0
))

function records(value: unknown): DataRecord[] {
  return Array.isArray(value)
    ? value.filter((item): item is DataRecord => !!item && typeof item === 'object')
    : []
}

function text(value: unknown): string {
  return String(value ?? '').trim()
}

function label(value: unknown): string {
  return text(value).replace(/_/g, ' ')
}

function fileTitle(item: DataRecord): string {
  return text(item.filename) || text(item.path) || text(item.file_id) || 'File'
}

function score(value: unknown): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return ''
  return `${Math.round(numeric * 100)}% match`
}

function activityTitle(item: DataRecord): string {
  if (text(item.tool_type) === 'mcp') {
    return [text(item.server_label), text(item.name)].filter(Boolean).join(' / ') || 'MCP call'
  }
  return label(item.tool_type) || 'Tool activity'
}

function toolTitle(item: DataRecord): string {
  return text(item.name) || label(item.type) || 'Tool'
}

function filePatches(item: DataRecord): ParsedFilePatch[] {
  return Array.isArray(item.patches) ? item.patches as ParsedFilePatch[] : []
}

function activitySummary(item: DataRecord): string {
  if (item.action && typeof item.action === 'object') {
    const actionType = label(item.action.type)
    const coordinates = Number.isFinite(Number(item.action.x)) && Number.isFinite(Number(item.action.y))
      ? ` (${item.action.x}, ${item.action.y})`
      : ''
    return `${actionType}${coordinates}`.trim()
  }
  return ''
}

function resultText(item: DataRecord): string {
  const value = item.output ?? item.error ?? item.outputs
  if (value === undefined || value === null || value === '') return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function inputText(item: DataRecord): string {
  const value = item.arguments ?? item.input
  if (value === undefined || value === null || value === '') return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}
</script>

<template>
  <div v-if="hasInsights" class="tool-insights">
    <details v-if="availableTools.length" class="insight-section">
      <summary>Available tools ({{ availableTools.length }})</summary>
      <div class="insight-content">
        <article v-for="(item, index) in availableTools" :key="`${item.type}-${item.name}-${index}`" class="insight-card">
          <div class="card-head">
            <strong>{{ toolTitle(item) }}</strong>
            <span>{{ label(item.type) }}</span>
          </div>
          <p v-if="item.description" class="tool-description">{{ item.description }}</p>
          <div v-if="typeof item.strict === 'boolean'" class="card-meta">Strict schema: {{ item.strict ? 'yes' : 'no' }}</div>
          <details v-if="item.configuration && typeof item.configuration === 'object'" class="inline-details">
            <summary>Schema and configuration</summary>
            <pre>{{ JSON.stringify(item.configuration, null, 2) }}</pre>
          </details>
        </article>
      </div>
    </details>

    <details v-if="fileReferences.length" class="insight-section">
      <summary>Referenced files ({{ fileReferences.length }})</summary>
      <div class="insight-content">
        <article v-for="(item, index) in fileReferences" :key="`${item.file_id || item.filename}-${index}`" class="insight-card">
          <div class="card-head">
            <strong>{{ fileTitle(item) }}</strong>
            <span v-if="score(item.score)">{{ score(item.score) }}</span>
          </div>
          <div class="card-meta">
            <span>{{ label(item.source) }}</span>
            <span v-if="item.file_id">{{ item.file_id }}</span>
          </div>
          <div v-if="Array.isArray(item.queries) && item.queries.length" class="card-meta">
            Query: {{ item.queries.join(' · ') }}
          </div>
          <blockquote v-if="item.text" class="file-snippet">{{ item.text }}</blockquote>
        </article>
      </div>
    </details>

    <details v-if="fileChanges.length" class="insight-section">
      <summary>File changes ({{ fileChanges.length }})</summary>
      <div class="insight-content">
        <article v-for="(item, index) in fileChanges" :key="`${item.call_id}-${item.path}-${index}`" class="insight-card file-change">
          <div class="card-head">
            <strong>{{ item.path }}</strong>
            <span :class="['operation', `operation-${item.operation}`]">{{ label(item.operation) }}</span>
          </div>
          <div class="card-meta">{{ label(item.status) }}</div>
          <ResponseFileDiff v-if="filePatches(item).length" :patches="filePatches(item)" />
          <details v-else-if="item.diff" class="inline-details">
            <summary>Raw patch</summary>
            <pre>{{ item.diff }}</pre>
          </details>
          <details v-if="Array.isArray(item.outputs) && item.outputs.length" class="inline-details">
            <summary>Execution result</summary>
            <pre>{{ JSON.stringify(item.outputs, null, 2) }}</pre>
          </details>
        </article>
      </div>
    </details>

    <details v-if="commands.length" class="insight-section">
      <summary>Commands ({{ commands.length }})</summary>
      <div class="insight-content">
        <article v-for="(item, index) in commands" :key="`${item.call_id}-${index}`" class="insight-card">
          <div class="card-head">
            <strong>{{ label(item.tool_type) }}</strong>
            <span>{{ label(item.status) }}</span>
          </div>
          <div v-if="item.working_directory" class="card-meta">Working directory: {{ item.working_directory }}</div>
          <ResponseCommandExecution :command="item" />
        </article>
      </div>
    </details>

    <details v-if="toolActivities.length" class="insight-section">
      <summary>Tool results ({{ toolActivities.length }})</summary>
      <div class="insight-content">
        <article v-for="(item, index) in toolActivities" :key="`${item.call_id}-${index}`" class="insight-card">
          <div class="card-head">
            <strong>{{ activityTitle(item) }}</strong>
            <span>{{ label(item.status) }}</span>
          </div>
          <div v-if="activitySummary(item)" class="card-meta">{{ activitySummary(item) }}</div>
          <details v-if="inputText(item)" class="inline-details">
            <summary>Input</summary>
            <pre>{{ inputText(item) }}</pre>
          </details>
          <details v-if="item.code" class="inline-details">
            <summary>Code</summary>
            <pre>{{ item.code }}</pre>
          </details>
          <details v-if="resultText(item)" class="inline-details">
            <summary>Result</summary>
            <pre>{{ resultText(item) }}</pre>
          </details>
          <details v-if="Array.isArray(item.pending_safety_checks) && item.pending_safety_checks.length" class="inline-details warning">
            <summary>Pending safety checks</summary>
            <pre>{{ JSON.stringify(item.pending_safety_checks, null, 2) }}</pre>
          </details>
        </article>
      </div>
    </details>
  </div>
</template>

<style scoped>
.tool-insights {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.insight-section {
  min-width: 0;
}

.insight-section > summary {
  cursor: pointer;
  color: rgba(186, 230, 253, 0.9);
  font-size: 11px;
  font-weight: 700;
}

.insight-section[open] > summary {
  position: sticky;
  top: 0;
  z-index: 40;
  margin: 0 -4px;
  padding: 5px 4px;
  border-radius: 5px;
  background: rgba(9, 38, 57, 0.98);
  box-shadow: 0 4px 8px rgba(2, 6, 23, 0.22);
}

.insight-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
  min-width: 0;
}

.insight-card {
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid rgba(125, 211, 252, 0.12);
  border-radius: 7px;
  background: rgba(15, 23, 42, 0.28);
}

.file-change {
  border-color: rgba(167, 139, 250, 0.2);
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  color: rgba(226, 232, 240, 0.94);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.card-head span,
.card-meta {
  color: rgba(148, 163, 184, 0.88);
  font-size: 10px;
}

.card-meta {
  display: flex;
  gap: 8px;
  margin-top: 3px;
  overflow-wrap: anywhere;
}

.operation {
  flex: 0 0 auto;
  padding: 1px 5px;
  border-radius: 999px;
  background: rgba(139, 92, 246, 0.16);
  color: rgba(216, 180, 254, 0.94) !important;
}

.operation-create_file {
  background: rgba(34, 197, 94, 0.14);
  color: rgba(134, 239, 172, 0.94) !important;
}

.operation-delete_file {
  background: rgba(239, 68, 68, 0.14);
  color: rgba(252, 165, 165, 0.94) !important;
}

.file-snippet {
  max-height: 92px;
  margin: 6px 0 0;
  padding-left: 7px;
  overflow: auto;
  border-left: 2px solid rgba(56, 189, 248, 0.3);
  color: rgba(203, 213, 225, 0.82);
  white-space: pre-wrap;
  font-size: 10px;
}

.tool-description {
  margin: 5px 0 0;
  color: rgba(203, 213, 225, 0.82);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 10px;
  line-height: 1.45;
}

.command-text,
.inline-details pre {
  max-height: 220px;
  margin: 6px 0 0;
  padding: 7px;
  overflow: auto;
  border-radius: 6px;
  background: rgba(2, 6, 23, 0.46);
  color: rgba(203, 213, 225, 0.9);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 10px;
}

.inline-details {
  margin-top: 6px;
}

.inline-details summary {
  cursor: pointer;
  color: rgba(125, 211, 252, 0.88);
  font-size: 10px;
}

.inline-details.warning summary {
  color: rgba(253, 186, 116, 0.94);
}
</style>
