<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ActionButton from '../ActionButton.vue'
import SelectionButton from '../SelectionButton.vue'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'
import {
  getTurnAudit,
  listTurnAudits,
  type TurnAuditDetailDocument,
  type TurnAuditListDocument,
  type TurnAuditSummary,
  type TurnAuditTimelineEntry,
} from '../../settingsApi'

type AuditArtifact = {
  name?: string
  path?: string
  size?: number
  content?: string
  too_large?: boolean
}

const startDate = ref(localDate())
const endDate = ref(localDate())
const graphId = ref('')
const nodeId = ref('')
const catalog = ref<TurnAuditListDocument | null>(null)
const selectedTraceId = ref('')
const detail = ref<TurnAuditDetailDocument | null>(null)
const loadingList = ref(false)
const loadingDetail = ref(false)
const error = ref('')

const turns = computed(() => catalog.value?.turns || [])
const selectedTurn = computed(() => {
  return turns.value.find((turn) => turn.trace_id === selectedTraceId.value) || null
})

function localDate() {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function shortText(value: unknown, max = 110) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function durationText(value: number | null | undefined) {
  if (value == null) return '-'
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(1)} s`
}

function formatDetails(entry: TurnAuditTimelineEntry) {
  const details = { ...entry.details }
  delete details.artifacts
  return JSON.stringify(details, null, 2)
}

function entryArtifacts(entry: TurnAuditTimelineEntry): AuditArtifact[] {
  const value = entry.details.artifacts
  return Array.isArray(value) ? value as AuditArtifact[] : []
}

async function loadTurns() {
  loadingList.value = true
  error.value = ''
  try {
    const next = await listTurnAudits(
      startDate.value,
      endDate.value,
      graphId.value,
      nodeId.value,
    )
    catalog.value = next
    const selectedStillExists = next.turns.some((turn) => turn.trace_id === selectedTraceId.value)
    if (!selectedStillExists) {
      selectedTraceId.value = next.turns[0]?.trace_id || ''
    }
    if (selectedTraceId.value) {
      await loadDetail(next.turns.find((turn) => turn.trace_id === selectedTraceId.value) || null)
    } else {
      detail.value = null
    }
  } catch (e: any) {
    error.value = String(e?.message || e)
    detail.value = null
  } finally {
    loadingList.value = false
  }
}

async function loadDetail(turn: TurnAuditSummary | null) {
  if (!turn) {
    detail.value = null
    return
  }
  selectedTraceId.value = turn.trace_id
  loadingDetail.value = true
  error.value = ''
  try {
    detail.value = await getTurnAudit(turn.trace_id, turn.graph_id, turn.node_id)
  } catch (e: any) {
    error.value = String(e?.message || e)
    detail.value = null
  } finally {
    loadingDetail.value = false
  }
}

function changeScope() {
  selectedTraceId.value = ''
  detail.value = null
  void loadTurns()
}

onMounted(loadTurns)
</script>

<template>
  <div class="turn-audit settings-split">
    <aside class="settings-split__side">
      <div class="audit-filters">
        <label class="audit-date-filter">
          From
          <FormTextInput v-model="startDate" type="date" />
        </label>
        <label class="audit-date-filter">
          To
          <FormTextInput v-model="endDate" type="date" />
        </label>
        <label>
          Graph
          <FormSelect v-model="graphId" @change="changeScope">
            <option value="">All graphs</option>
            <option v-for="item in catalog?.available_graph_ids || []" :key="item" :value="item">{{ item }}</option>
          </FormSelect>
        </label>
        <label>
          Node
          <FormSelect v-model="nodeId" @change="changeScope">
            <option value="">All nodes</option>
            <option v-for="item in catalog?.available_node_ids || []" :key="item" :value="item">{{ item }}</option>
          </FormSelect>
        </label>
        <ActionButton class="audit-filter-action" compact block :disabled="loadingList" @click="loadTurns">
          {{ loadingList ? 'Loading...' : 'Reload' }}
        </ActionButton>
      </div>

      <div class="settings-split__items">
        <SelectionButton
          v-for="turn in turns"
          :key="`${turn.graph_id}:${turn.node_id}:${turn.trace_id}`"
          stacked
          class="audit-turn settings-list-item"
          :active="selectedTraceId === turn.trace_id"
          @click="loadDetail(turn)"
        >
          <span class="audit-turn-top">
            <strong>{{ turn.node_id }}</strong>
            <small :class="turn.audit_completeness">{{ turn.audit_completeness }}</small>
          </span>
          <template #detail>
            <span class="settings-list-item__lines">
              <span>{{ shortText(turn.question || turn.answer_preview) }}</span>
              <small>{{ turn.started_at }} · {{ durationText(turn.duration_ms) }}</small>
              <small>{{ turn.tool_call_count + turn.server_tool_call_count }} tools · {{ turn.provider_id }}</small>
            </span>
          </template>
        </SelectionButton>
        <div v-if="!turns.length && !loadingList" class="audit-empty">No runs for this date range.</div>
      </div>
    </aside>

    <main class="turn-audit-main settings-split__detail">
      <div v-if="loadingDetail" class="audit-empty">Loading audit...</div>
      <template v-else-if="detail && selectedTurn">
        <header class="audit-head">
          <div>
            <h2>{{ selectedTurn.graph_id }} / {{ selectedTurn.node_id }}</h2>
            <span>{{ selectedTurn.trace_id }}</span>
          </div>
          <span class="audit-badge" :class="detail.turn.audit_completeness">
            {{ detail.turn.audit_completeness }}
          </span>
        </header>

        <div class="audit-metrics">
          <div><span>Status</span><strong>{{ detail.turn.status }}</strong></div>
          <div><span>Duration</span><strong>{{ durationText(detail.turn.duration_ms) }}</strong></div>
          <div><span>Model rounds</span><strong>{{ detail.model_rounds.length }}</strong></div>
          <div><span>Tool calls</span><strong>{{ detail.tool_calls.length + detail.server_tool_calls.length }}</strong></div>
          <div><span>Files changed</span><strong>{{ detail.file_changes.length }}</strong></div>
        </div>

        <section v-if="detail.file_changes.length" class="audit-files">
          <h3>Persisted file changes</h3>
          <div v-for="change in detail.file_changes" :key="`${change.call_id}:${change.path}`">
            <span>{{ change.operation }}</span>
            <code>{{ change.path }}</code>
          </div>
        </section>

        <section class="audit-timeline">
          <h3>Timeline</h3>
          <article
            v-for="entry in detail.timeline"
            :key="entry.id"
            class="audit-event"
            :class="entry.kind"
          >
            <div class="audit-event-marker"></div>
            <div class="audit-event-body">
              <header>
                <strong>{{ entry.title }}</strong>
                <span>{{ entry.status }}</span>
                <time>{{ entry.at }}</time>
              </header>
              <p v-if="entry.summary">{{ entry.summary }}</p>
              <details>
                <summary>Raw details</summary>
                <pre>{{ formatDetails(entry) }}</pre>
              </details>
              <details
                v-for="artifact in entryArtifacts(entry)"
                :key="artifact.path"
                class="audit-artifact"
              >
                <summary>{{ artifact.name }} · {{ artifact.size || 0 }} bytes</summary>
                <pre>{{ artifact.too_large ? `Artifact is larger than the review limit: ${artifact.path}` : artifact.content }}</pre>
              </details>
            </div>
          </article>
        </section>
      </template>
      <div v-else-if="!error" class="audit-empty">Select a run to review its complete chain.</div>
      <div v-if="error" class="audit-error">{{ error }}</div>
    </main>
  </div>
</template>

<style scoped src="./TurnAuditPanel.css"></style>
