<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { listMobileNodes, type MobileNode } from '../api'
import { groupApi, type AgentGroup } from '../groups/groupApi'
import GroupBoardPanel from '../groups/GroupBoardPanel.vue'
import { subscribeAppEvents } from '../composables/useAppEventStream'
import { cloudBoardSession } from '../portal/boardSession'

const props = defineProps<{ graphId: string; pcId: string }>()
const session = inject(cloudBoardSession, null)
const ready = computed(() => !session || session.phase.value === 'ready')
const groups = ref<AgentGroup[]>([])
const activeId = ref<string | null>(null)
const active = computed(() => groups.value.find(group => group.id === activeId.value) || null)
const nodes = ref<Record<string, MobileNode>>({})
const error = ref('')
let generation = 0, requestVersion = 0
let interval: ReturnType<typeof setInterval> | undefined
let restored = false

function storeLocation(id: string | null) {
  const url = new URL(window.location.href)
  if (id) {
    url.searchParams.set('mobile_graph', props.graphId)
    url.searchParams.set('mobile_group', id)
    url.searchParams.delete('mobile_node')
  } else url.searchParams.delete('mobile_group')
  window.history.replaceState(window.history.state, '', url)
}
function open(group: AgentGroup) { activeId.value = group.id; storeLocation(group.id); void refresh() }
function close() { activeId.value = null; storeLocation(null) }
async function refresh(restoring = false) {
  if (!ready.value && !restoring) return
  const epoch = generation, version = ++requestVersion
  try {
    const result = await groupApi.list(props.graphId)
    if (epoch !== generation || version !== requestVersion) return
    error.value = ''
    groups.value = result.groups
    if (!restored) {
      restored = true
      const url = new URL(window.location.href)
      const saved = url.searchParams.get('mobile_group')
      if (url.searchParams.get('mobile_graph') === props.graphId && saved) {
        if (result.groups.some(group => group.id === saved)) activeId.value = saved
        else { error.value = '这个组已不存在或不可访问。'; storeLocation(null) }
      }
    }
    if (activeId.value && !result.groups.some(group => group.id === activeId.value)) close()
    if (activeId.value) {
      const entries = await listMobileNodes(props.pcId, props.graphId)
      if (epoch !== generation || version !== requestVersion) return
      nodes.value = Object.fromEntries(entries.map(node => [node.id, node]))
    }
  } catch (cause) {
    if (epoch === generation && version === requestVersion) {
      if (restoring) throw cause
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }
}
watch([() => props.pcId, () => props.graphId], () => {
  generation++; groups.value = []; activeId.value = null; nodes.value = {}; restored = false; error.value = ''
  void refresh()
}, { immediate: true })
watch(activeId, value => {
  clearInterval(interval)
  if (value) interval = setInterval(() => { void refresh() }, 5000)
})
watch(ready, value => { if (value) void refresh() })
const unsubscribe = subscribeAppEvents(event => {
  if (event.event === 'stream_snapshot' || event.event === 'stream_gap' ||
      (event.event === 'groups_changed' && event.graph_id === props.graphId)) void refresh()
})
const unregister = session?.register({
  suspend() { generation++ },
  restore: () => refresh(true),
})
onBeforeUnmount(() => { generation++; clearInterval(interval); unsubscribe(); unregister?.() })
</script>
<template>
  <section v-if="groups.length || error" class="mobile-groups" aria-label="Group 群聊">
    <p v-if="error" class="group-error" role="alert">{{ error }} <button @click="error = ''; refresh()">重试</button></p>
    <button v-for="group in groups" :key="group.id" class="mobile-group-entry" @click="open(group)">
      <span><strong>{{ group.name }}</strong><small>Group · {{ group.members.length }} 位成员 · 进入群聊</small></span><span aria-hidden="true">›</span>
    </button>
    <GroupBoardPanel :group="active" :graph-id="graphId" :node-configs="nodes" :ready="ready" chat-only @close="close" @updated="refresh()" />
  </section>
</template>
<style scoped>
.mobile-groups { display: grid; gap: 8px; margin: 8px 0 14px; }
.mobile-group-entry { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; padding: 15px; text-align: left; background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border-medium); border-radius: 14px; }
strong { display: block; font-size: 16px; } small { display: block; margin-top: 6px; color: var(--text-secondary); }
.group-error { color: var(--accent-red); }
</style>
