<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getRuntimeEventDiagnostics, type RuntimeEventConfig, type RuntimeEventDiagnostics } from '../../api'
import {
  cloneRuntimeEventConfig,
  deleteRuntimeEventHandler,
  flattenRules,
  RUNTIME_EVENT_NAMES,
  RUNTIME_EVENT_TTLS,
} from '../../runtimeEventsConfig'

const COMPANION_GROUP_ID = 'companion'
const props = defineProps<{ data: Record<string, unknown> }>()
const emit = defineEmits<{ 'update:data': [value: Record<string, unknown>] }>()

const diagnostics = ref<RuntimeEventDiagnostics | null>(null)
const diagnosticsError = ref('')
const diagnosticsLoading = ref(false)
const config = computed(() => cloneRuntimeEventConfig(props.data) as RuntimeEventConfig)
const companionGroup = computed(() => config.value.receiver_groups?.[COMPANION_GROUP_ID] || null)
const handlers = computed(() => flattenRules(config.value.rules || {}))
const groupedHandlers = computed(() => {
  const eventOrder = new Map(RUNTIME_EVENT_NAMES.map((event, index) => [event, index]))
  const sorted = handlers.value.slice().sort((left, right) => {
    const eventDelta = (eventOrder.get(left.event as any) ?? 999) - (eventOrder.get(right.event as any) ?? 999)
    return eventDelta || left.graphId.localeCompare(right.graphId) || left.nodeId.localeCompare(right.nodeId) || left.handlerIndex - right.handlerIndex
  })
  const groups: Array<{
    event: string
    count: number
    graphs: Array<{
      graphId: string
      nodes: Array<{ nodeId: string; handlerIndex: number; handler: (typeof sorted)[number]['handler'] }>
    }>
  }> = []
  for (const item of sorted) {
    let eventGroup = groups.find((group) => group.event === item.event)
    if (!eventGroup) {
      eventGroup = { event: item.event, count: 0, graphs: [] }
      groups.push(eventGroup)
    }
    let graphGroup = eventGroup.graphs.find((group) => group.graphId === item.graphId)
    if (!graphGroup) {
      graphGroup = { graphId: item.graphId, nodes: [] }
      eventGroup.graphs.push(graphGroup)
    }
    graphGroup.nodes.push({ nodeId: item.nodeId, handlerIndex: item.handlerIndex, handler: item.handler })
    eventGroup.count += item.handler.enabled === false ? 0 : 1
  }
  return groups
})
const compiledText = computed(() => {
  const compiled = diagnostics.value?.compiled || {}
  return [`${compiled.enabled_rules ?? compiled.rules ?? 0} enabled handlers`, `${compiled.source_nodes ?? 0} nodes`, `${compiled.receiver_groups ?? 0} receiver groups`].join(' / ')
})

function emitConfig(next: RuntimeEventConfig) {
  emit('update:data', next as unknown as Record<string, unknown>)
}

function ensureCompanionGroup(next: RuntimeEventConfig) {
  if (!next.receiver_groups) next.receiver_groups = {}
  if (!next.receiver_groups[COMPANION_GROUP_ID]) {
    next.receiver_groups[COMPANION_GROUP_ID] = {
      enabled: true,
      graph_id: 'Companion',
      merge_target: { graph_id: 'Companion', node_id: 'Companion' },
      receivers: [],
    }
  }
  return next.receiver_groups[COMPANION_GROUP_ID]
}

function updateRoot(key: keyof RuntimeEventConfig, value: unknown) {
  const next = cloneRuntimeEventConfig(config.value)
  ;(next as Record<string, unknown>)[key] = value
  emitConfig(next)
}

function updatePolicy(key: string, value: unknown) {
  const next = cloneRuntimeEventConfig(config.value)
  const policy = { ...(next.context_policy || {}) }
  if (value === '' || value === null || value === undefined) delete policy[key]
  else policy[key] = value
  next.context_policy = policy
  emitConfig(next)
}

function updateReceiver(index: number, key: 'graph_id' | 'node_id', value: string) {
  const next = cloneRuntimeEventConfig(config.value)
  const group = ensureCompanionGroup(next)
  const receivers = [...(group.receivers || [])]
  receivers[index] = { ...(receivers[index] || { graph_id: 'Companion', node_id: '' }), [key]: value }
  group.receivers = receivers
  emitConfig(next)
}

function addReceiver() {
  const next = cloneRuntimeEventConfig(config.value)
  const group = ensureCompanionGroup(next)
  group.receivers = [...(group.receivers || []), { graph_id: 'Companion', node_id: '' }]
  emitConfig(next)
}

function deleteReceiver(index: number) {
  const next = cloneRuntimeEventConfig(config.value)
  const group = ensureCompanionGroup(next)
  group.receivers = (group.receivers || []).filter((_receiver, itemIndex) => itemIndex !== index)
  emitConfig(next)
}

function deleteHandler(event: string, graphId: string, nodeId: string, handlerIndex: number) {
  const next = cloneRuntimeEventConfig(config.value)
  deleteRuntimeEventHandler(next, { event, graphId, nodeId, handlerIndex })
  emitConfig(next)
}

async function refreshDiagnostics() {
  diagnosticsLoading.value = true
  diagnosticsError.value = ''
  try {
    diagnostics.value = await getRuntimeEventDiagnostics()
  } catch (error: any) {
    diagnosticsError.value = String(error?.message || error)
  } finally {
    diagnosticsLoading.value = false
  }
}

onMounted(refreshDiagnostics)
</script>

<template>
  <div class="runtime-events-form">
    <section class="settings-group">
      <div class="group-head">
        <h2>Runtime Events</h2>
        <button type="button" @click="refreshDiagnostics">{{ diagnosticsLoading ? 'Refreshing...' : 'Refresh' }}</button>
      </div>
      <div class="form-grid">
        <label class="checkbox-label"><span>Enabled</span><input :checked="config.enabled" type="checkbox" @change="updateRoot('enabled', ($event.target as HTMLInputElement).checked)" /></label>
        <label><span>Default TTL</span><select :value="String(config.context_policy?.default_ttl || 'next_turn')" @change="updatePolicy('default_ttl', ($event.target as HTMLSelectElement).value)"><option v-for="ttl in RUNTIME_EVENT_TTLS" :key="ttl" :value="ttl">{{ ttl }}</option></select></label>
        <label><span>Max Fragment Chars</span><input :value="String(config.context_policy?.max_fragment_chars || 8000)" type="number" min="1" @input="updatePolicy('max_fragment_chars', Number(($event.target as HTMLInputElement).value || 0))" /></label>
        <label><span>Dedupe Window Ms</span><input :value="String(config.context_policy?.dedupe_window_ms || 30000)" type="number" min="0" @input="updatePolicy('dedupe_window_ms', Number(($event.target as HTMLInputElement).value || 0))" /></label>
      </div>
      <div class="diagnostics-line"><span>{{ diagnostics ? compiledText : 'Diagnostics not loaded' }}</span><span v-if="diagnosticsError" class="inline-error">{{ diagnosticsError }}</span></div>
    </section>

    <section class="settings-group">
      <div class="group-head"><h2>Explicit Receivers</h2><button type="button" @click="addReceiver">Add Receiver</button></div>
      <div class="receiver-list">
        <div v-for="(receiver, index) in companionGroup?.receivers || []" :key="index" class="receiver-row">
          <input :value="receiver.graph_id || 'Companion'" placeholder="Graph" @input="updateReceiver(index, 'graph_id', ($event.target as HTMLInputElement).value)" />
          <input :value="receiver.node_id || ''" placeholder="Node" @input="updateReceiver(index, 'node_id', ($event.target as HTMLInputElement).value)" />
          <button type="button" class="danger" @click="deleteReceiver(index)">Delete</button>
        </div>
        <div v-if="!(companionGroup?.receivers || []).length" class="empty-hint">No explicit receivers. A dispatch handler can create a temporary Companion node from its Agent Profile.</div>
      </div>
    </section>

    <section class="settings-group">
      <div class="group-head"><h2>Node Event Handlers</h2><span class="small-count">{{ handlers.length }}</span></div>
      <div class="node-route-tree">
        <div v-for="eventGroup in groupedHandlers" :key="eventGroup.event" class="event-route-group">
          <div class="event-route-head"><span class="event-name">{{ eventGroup.event }}</span><span class="route-count">{{ eventGroup.count }} enabled</span></div>
          <div v-for="graphGroup in eventGroup.graphs" :key="`${eventGroup.event}/${graphGroup.graphId}`" class="graph-route-group">
            <div class="graph-route-head">{{ graphGroup.graphId }}</div>
            <div v-for="node in graphGroup.nodes" :key="`${node.nodeId}/${node.handlerIndex}`" class="node-route-row">
              <span class="route-source">{{ node.nodeId }} #{{ node.handlerIndex + 1 }}</span>
              <span>{{ node.handler.action }}</span>
              <span>{{ node.handler.action === 'node.dispatch' ? (node.handler.params?.profile_ids || []).join(', ') : (node.handler.action === 'context.append_file' ? `${(node.handler.params?.paths || []).join(', ')} (${node.handler.params?.role || 'developer'})` : node.handler.target) }}</span>
              <span>{{ node.handler.enabled === false ? 'disabled' : 'enabled' }}</span>
              <button type="button" class="danger" @click="deleteHandler(eventGroup.event, graphGroup.graphId, node.nodeId, node.handlerIndex)">Delete</button>
            </div>
          </div>
        </div>
        <div v-if="!handlers.length" class="empty-hint">No node event handlers configured.</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.runtime-events-form { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 14px; padding-right: 4px; }
.settings-group { border: 1px solid rgba(148, 163, 184, 0.18); border-radius: 8px; padding: 12px; background: rgba(15, 23, 42, 0.28); }
.group-head, .diagnostics-line { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.settings-group h2 { margin: 0; font-size: 15px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 12px; margin-top: 10px; }
.receiver-list, .node-route-tree { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.receiver-row, .event-route-group, .graph-route-group, .node-route-row { display: grid; align-items: center; gap: 8px; border: 1px solid rgba(148, 163, 184, 0.14); border-radius: 8px; padding: 8px; font-size: 12px; }
.receiver-row { grid-template-columns: 1fr 1fr auto; }
.event-route-group, .graph-route-group { display: flex; flex-direction: column; align-items: stretch; }
.event-route-group { padding: 9px; gap: 8px; }
.graph-route-group { margin-left: 12px; padding: 8px; gap: 7px; border-style: dashed; }
.event-route-head { display: grid; grid-template-columns: 180px 100px; align-items: center; gap: 8px; font-size: 12px; }
.graph-route-head { font-family: Consolas, Menlo, monospace; color: #bae6fd; }
.node-route-row { grid-template-columns: minmax(180px, 1fr) 140px minmax(160px, 1fr) 90px auto; }
.event-name, .route-source { font-family: Consolas, Menlo, monospace; color: #bfdbfe; overflow-wrap: anywhere; }
.route-count, .small-count, .empty-hint, .diagnostics-line { color: rgba(148, 163, 184, 0.9); font-size: 12px; }
.inline-error { color: #fca5a5; }
label { color: rgba(226, 232, 240, 0.94); font-size: 12px; }
.checkbox-label { display: flex; flex-direction: column; gap: 5px; }
.checkbox-label input { width: auto; align-self: flex-start; }
input, select { width: 100%; border: 1px solid rgba(148, 163, 184, 0.24); border-radius: 8px; padding: 8px 9px; color: rgba(226, 232, 240, 0.96); background: rgba(2, 6, 23, 0.5); font: inherit; }
button { border: 1px solid rgba(148, 163, 184, 0.26); border-radius: 8px; background: rgba(15, 23, 42, 0.92); color: #f8fafc; cursor: pointer; padding: 7px 10px; font-size: 12px; }
button.danger { border-color: rgba(248, 113, 113, 0.35); color: rgba(254, 202, 202, 0.95); }
@media (max-width: 1120px) { .form-grid, .receiver-row, .event-route-head, .node-route-row { grid-template-columns: 1fr; } .graph-route-group { margin-left: 0; } }
</style>
