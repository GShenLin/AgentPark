<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getActiveApiBase, listNodeInstanceConfigs, type GraphInfo, type NodeInstanceConfig } from '../../api'
import { groupApi, type AgentGroup } from '../../groups/groupApi'
import { subscribeAppEvents } from '../../composables/useAppEventStream'
import { graphHierarchy } from './graphHierarchy'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import { t } from '../../i18n'

const props = defineProps<{ graph: GraphInfo; refreshKey: GraphInfo[] }>()
const emit = defineEmits<{ navigateNode: [nodeId: string]; openGroup: [groupId: string] }>()
const nodes = ref<NodeInstanceConfig[]>([])
const groups = ref<AgentGroup[]>([])
const expandedGroups = ref(new Set<string>())
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const hierarchy = computed(() => graphHierarchy(nodes.value, groups.value))
let revision = 0
let disposed = false
let refreshTimer: ReturnType<typeof setTimeout> | undefined
const structureEvents = new Set(['groups_changed', 'graph_changed', 'graph_save_api',
  'node_renamed', 'node_deleted', 'node_cloned', 'node_moved_in', 'node_moved_out'])

async function refresh() {
  const version = ++revision
  const graphId = props.graph.id
  const base = getActiveApiBase()
  loading.value = true; error.value = ''
  try {
    const [nodeResult, groupResult] = await Promise.all([
      listNodeInstanceConfigs(graphId, 0, 'board'), groupApi.list(graphId),
    ])
    if (disposed || version !== revision || graphId !== props.graph.id || base !== getActiveApiBase()) return
    nodes.value = nodeResult.nodes
    groups.value = groupResult.groups
    expandedGroups.value = new Set([...expandedGroups.value].filter(id => groups.value.some(g => g.id === id)))
  } catch (cause) {
    if (!disposed && version === revision) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (!disposed && version === revision) loading.value = false
  }
}
function toggleMembers(id: string) {
  const next = new Set(expandedGroups.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  expandedGroups.value = next
}
async function dissolve(group: AgentGroup) {
  busy.value = true; error.value = ''
  try {
    await groupApi.dissolve(props.graph.id, group.id, group.revision)
    await refresh()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { busy.value = false }
}
const unsubscribe = subscribeAppEvents(event => {
  if (event.event === 'stream_gap' || event.event === 'stream_snapshot' ||
      (event.graph_id === props.graph.id && structureEvents.has(String(event.event)))) {
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => { void refresh() }, 80)
  }
})
watch(() => [props.graph.id, props.refreshKey], () => { void refresh() }, { immediate: true })
onBeforeUnmount(() => { disposed = true; revision++; unsubscribe(); if (refreshTimer) clearTimeout(refreshTimer) })
</script>

<template>
  <div class="graph-contents" :aria-label="`${graph.name} · ${t('memory.graphContents')}`">
    <p v-if="loading && !groups.length && !nodes.length" role="status">{{ t('memory.loadingGraphContents') }}</p>
    <div v-if="error" role="alert">{{ error }} <ActionButton compact @click="refresh">{{ t('common.refresh') }}</ActionButton></div>
    <template v-else-if="!loading || groups.length || nodes.length">
      <header><strong>Groups</strong><span>{{ groups.length }}</span></header>
      <p v-if="!groups.length">{{ t('memory.noGraphGroups') }}</p>
      <section v-for="entry in hierarchy.groups" :key="entry.group.id" class="graph-group">
        <div class="graph-group-row">
          <button class="members-toggle" :aria-label="t('memory.toggleMembers', { name: entry.group.name })"
            :aria-expanded="expandedGroups.has(entry.group.id)" @click="toggleMembers(entry.group.id)">
            {{ expandedGroups.has(entry.group.id) ? '▾' : '▸' }}
          </button>
          <button class="group-entry" :title="t('memory.openGroupChat')" @click="emit('openGroup', entry.group.id)">
            <span class="entry-title"><small>Group</small><strong>{{ entry.group.name }}</strong></span>
            <span>{{ t('memory.groupMembersCount', { count: entry.members.length }) }} · {{ t('memory.completedTasks', {
              done: entry.group.tasks.filter(task => task.status === 'done').length, total: entry.group.tasks.length,
            }) }}</span>
          </button>
          <DangerButton compact :disabled="busy" :aria-label="t('memory.dissolveGroup', { name: entry.group.name })"
            :title="t('memory.dissolveGroupHint')" @click="dissolve(entry.group)">{{ t('memory.dissolve') }}</DangerButton>
        </div>
        <div v-if="expandedGroups.has(entry.group.id)" class="group-members">
          <button v-for="member in entry.members" :key="member.node_id" class="node-entry" :disabled="!member.node"
            @click="emit('navigateNode', member.node_id)">
            <span class="entry-title"><small>Node</small><span>{{ member.node?.name || member.node_id }}</span></span>
            <small v-if="member.role">{{ member.role }}</small>
            <small v-if="!member.node">{{ t('memory.nodeUnavailable') }}</small>
          </button>
        </div>
      </section>
      <header><strong>{{ t('memory.ungroupedNodes') }}</strong><span>{{ hierarchy.ungrouped.length }}</span></header>
      <p v-if="!hierarchy.ungrouped.length">{{ t('memory.noUngroupedNodes') }}</p>
      <button v-for="node in hierarchy.ungrouped" :key="node.node_id" class="node-entry" @click="emit('navigateNode', node.node_id)">
        <span class="entry-title"><small>Node</small><span>{{ node.name || node.node_id }}</span></span>
        <small>{{ node.type_id }}</small>
      </button>
    </template>
  </div>
</template>

<style scoped>
.graph-contents { display: grid; gap: 7px; margin: 0 0 8px 16px; padding: 8px 0 4px 12px; border-left: 1px solid var(--ui-control-border); min-width: 0; }
header { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 12px; margin-top: 5px; }
p, header span, small, .group-entry > span:last-child { margin: 0; color: var(--text-secondary); font-size: 11px; line-height: 1.6; }
.graph-group-row { display: flex; gap: 5px; align-items: center; min-width: 0; }
.members-toggle { flex-shrink: 0; width: 25px; padding: 6px 2px; border: none; background: transparent; color: inherit; cursor: pointer; }
.group-entry, .node-entry { display: flex; flex-direction: column; gap: 3px; align-items: stretch; text-align: left; border: 1px solid var(--ui-control-border); background: transparent; color: var(--text-primary); border-radius: 8px; padding: 8px; cursor: pointer; min-width: 0; }
.group-entry { flex: 1; }
.entry-title { display: flex; gap: 6px; align-items: baseline; min-width: 0; }
.entry-title small { flex-shrink: 0; font-size: 10px; }
.entry-title strong, .entry-title > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.group-members { display: grid; gap: 5px; margin: 8px 0 6px 12px; padding-left: 13px; border-left: 1px solid var(--ui-control-border); }
.node-entry { border-color: transparent; }
button:hover, button:focus-visible { background: var(--ui-control-background); }
button:focus-visible { outline: 2px solid var(--ui-control-focus); outline-offset: 1px; }
button:disabled { opacity: .55; cursor: default; }
[role=alert] { color: var(--accent-red); font-size: 12px; overflow-wrap: anywhere; }
</style>
