<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import ConversationWindow from '../components/ConversationWindow.vue'
import ConversationHeader from '../components/ConversationHeader.vue'
import ConversationComposerDock from '../components/ConversationComposerDock.vue'
import GroupComposer from './GroupComposer.vue'
import GroupEventAttachments from './GroupEventAttachments.vue'
import type { MessageResource } from '../composables/messageAttachments'
import { groupApi, type AgentGroup, type GroupDelivery, type GroupEvent, type GroupTask, type TaskStatus } from './groupApi'
import GroupMemberRole from './GroupMemberRole.vue'
import GroupPlanEditor from './GroupPlanEditor.vue'
import { useGroupScroll } from './useGroupScroll'
import GroupMessageStatus from './GroupMessageStatus.vue'
import GroupTaskList from './GroupTaskList.vue'

const props = withDefaults(defineProps<{ group: AgentGroup | null; graphId: string;
  nodeConfigs?: Record<string, { state?: string }>; chatOnly?: boolean; ready?: boolean }>(), { nodeConfigs: () => ({}), chatOnly: false, ready: true })
const emit = defineEmits<{ close: []; updated: [] }>()
const group = computed(() => props.group)
const error = ref('')
const events = ref<GroupEvent[]>([])
const deliveries = ref<GroupDelivery[]>([])
const mobileTab = ref<'tasks' | 'activity'>('activity')
const cursor = ref(0)
const hasOlder = ref(false)
const loadingOlder = ref(false)
const { body, following, onScroll, capture, restore, latest } = useGroupScroll()
let fetchingGeneration: number | null = null
let generation = 0
let interval: ReturnType<typeof setInterval> | undefined

const completed = computed(() => group.value?.tasks.filter(task => task.status === 'done').length ?? 0)
const newestEvents = computed(() => [...events.value].reverse())
const failedDelivery = computed(() => deliveries.value.filter(item => item.last_error))
const statusLabels: Record<TaskStatus, string> = { todo: '待处理', in_progress: '进行中', blocked: '受阻', done: '完成' }

async function refreshActivity() {
  const selected = group.value
  if (!selected || !props.ready) return
  const captured = generation
  if (fetchingGeneration === captured) return
  fetchingGeneration = captured
  const initial = cursor.value === 0
  try {
    const [history, delivery] = await Promise.all([
      groupApi.events(props.graphId, selected.id, cursor.value, { latest: initial }), groupApi.deliveries(props.graphId, selected.id),
    ])
    if (captured !== generation) return
    const position = capture()
    const byId = new Map(events.value.map(event => [event.seq, event]))
    for (const event of history.events) byId.set(event.seq, event)
    events.value = [...byId.values()].sort((a, b) => a.seq - b.seq)
    cursor.value = Math.max(cursor.value, history.cursor)
    deliveries.value = delivery.deliveries
    if (initial) hasOlder.value = history.has_older
    await restore(position, initial)
  } catch (reason) {
    if (captured === generation) error.value = String(reason instanceof Error ? reason.message : reason)
  } finally { if (fetchingGeneration === captured) fetchingGeneration = null }
}

async function loadOlder() {
  const selected = group.value, el = body.value
  if (!selected || !el || loadingOlder.value) return
  const captured = generation
  loadingOlder.value = true
  following.value = false
  try {
    const result = await groupApi.events(props.graphId, selected.id, 0, { before: events.value[0]?.seq })
    if (captured !== generation) return
    const position = capture()
    events.value = [...new Map([...result.events, ...events.value].map(e => [e.seq, e])).values()].sort((a,b) => a.seq-b.seq)
    hasOlder.value = result.has_older
    await restore(position)
  } catch (reason) { if (captured === generation) error.value = String(reason) }
  finally { if (captured === generation) loadingOlder.value = false }
}
async function onSent() { mobileTab.value = 'activity'; await refreshActivity(); await latest() }

watch([() => group.value?.id, () => props.graphId], () => {
  generation += 1
  clearInterval(interval)
  events.value = []; deliveries.value = []; cursor.value = 0; mobileTab.value = 'activity'; error.value = ''
  following.value = true; hasOlder.value = false; loadingOlder.value = false
  if (group.value) { void refreshActivity(); interval = setInterval(() => { void refreshActivity() }, 5000) }
}, { immediate: true })
watch(group, () => { void refreshActivity() })
watch(() => props.ready, ready => { generation++; if (ready) void refreshActivity() })
onBeforeUnmount(() => { generation += 1; clearInterval(interval) })

function memberStateLabel(state?: string) {
  const labels: Record<string, string> = { working: '正在处理', idle: '空闲', stop: '已暂停', pending: '等待处理' }
  return state ? labels[state] || state : '状态加载中'
}

function eventText(event: GroupEvent) {
  if (event.kind === 'message' || event.kind === 'reply' || event.kind === 'update') return String(event.payload.text)
  if (event.kind === 'member_renamed') return `${event.payload.old_node_id} 更名为 ${event.payload.node_id}`
  if (event.kind === 'member_role_updated') {
    const member = event.payload.member as { node_id: string; role: string }
    return `${member.node_id} 的角色更新为：${member.role || '未设角色'}`
  }
  const task = event.payload.task as GroupTask | undefined
  if (task) return `${task.title} · ${statusLabels[task.status]}`
  const labels: Record<string, string> = { group_created: '创建组', group_updated: '更新计划', member_joined: '成员加入', member_left: '成员离组', member_restored: '撤销删除，恢复组员与任务', group_visibility_changed: '组历史设为私有' }
  return labels[event.kind] ?? event.kind
}
</script>

<template>
  <ConversationWindow v-if="group" class="group-board-panel" :label="group.name" @close="emit('close')">
    <ConversationHeader :title="group.name" :subtitle="`共享任务面板 · ${completed}/${group.tasks.length} 任务完成`" close-label="关闭组面板" @close="emit('close')" />
    <nav class="group-mobile-tabs" aria-label="组面板栏目">
      <button :aria-pressed="mobileTab === 'tasks'" @click="mobileTab = 'tasks'">任务 {{ group.tasks.length - completed }}</button>
      <button :aria-pressed="mobileTab === 'activity'" @click="mobileTab = 'activity'">组内动态</button>
    </nav>
    <div class="group-board-columns" :data-mobile-tab="mobileTab">
      <section class="group-tasks-column" aria-label="任务栏">
        <GroupTaskList :key="`${graphId}:${group.id}`" :graph-id="graphId" :group="group" :events="events" :deliveries="deliveries"
          :node-configs="nodeConfigs" :ready="ready" @updated="emit('updated'); refreshActivity()" />
        <details class="group-team-details">
          <summary>成员与计划 · {{ group.members.length }} 位成员</summary>
          <GroupPlanEditor v-if="!chatOnly" :key="`${graphId}:${group.id}`" :graph-id="graphId" :group="group" @updated="emit('updated')" />
          <div class="group-members">
            <article v-for="member in group.members" :key="member.node_id"><strong>{{ member.node_id }}</strong><span>{{ memberStateLabel(nodeConfigs[member.node_id]?.state) }}</span>
              <GroupMemberRole v-if="!chatOnly" :key="`${graphId}:${group.id}:${member.node_id}`" :graph-id="graphId" :group-id="group.id" :member="member" @updated="emit('updated')" />
              <p>{{ group.tasks.filter(task => task.owner_id === member.node_id && task.status === 'in_progress').map(task => task.title).join('；') || (nodeConfigs[member.node_id]?.state === 'working' ? '正在处理消息' : '暂无进行中的任务') }}</p>
            </article>
          </div>
        </details>
      </section>
      <section class="group-activity-column" aria-label="组内动态栏">
        <header class="group-column-heading"><div><h3>组内动态</h3><span>最新在上</span></div><button @click="refreshActivity">刷新动态</button></header>
        <button v-if="!following" class="group-latest" @click="latest">回到最新 ↑</button>
        <div ref="body" class="group-board-body" @scroll="onScroll"><div class="group-board-content">
          <p v-if="!events.length" class="group-muted">暂无动态</p>
          <article v-for="event in newestEvents" :key="event.seq" :data-event-seq="event.seq" class="group-event">
            <div>{{ event.actor_id || '用户' }} <span>{{ event.created_at }}<template v-if="event.kind === 'reply' && (event.payload.task_ids as string[] | undefined)?.length"> · 任务答复</template><template v-if="event.kind === 'update'"> · 共享动态（不唤醒）</template><template v-if="event.payload.recipient_id"> → {{ event.payload.recipient_id }}</template></span></div>
            <p>{{ eventText(event) }}</p><GroupEventAttachments :resources="(event.payload.attachments || []) as MessageResource[]" />
            <GroupMessageStatus v-if="!event.actor_id && ['message', 'task_created', 'task_updated'].includes(event.kind)" :deliveries="deliveries.filter(item => item.event_seq === event.seq)" />
          </article>
          <button v-if="hasOlder" :disabled="loadingOlder" @click="loadOlder">{{ loadingOlder ? '加载中…' : '加载更早记录' }}</button>
          <details v-if="failedDelivery.length" class="group-delivery-errors"><summary>{{ failedDelivery.length }} 条通知有错误记录</summary><p v-for="item in failedDelivery" :key="`${item.event_seq}:${item.node_id}`">{{ item.node_id }} · #{{ item.event_seq }} · {{ item.last_error }}</p></details>
        </div></div>
      </section>
    </div>
    <ConversationComposerDock><template #status><p v-if="error" class="group-error" role="alert">{{ error }}</p></template><GroupComposer :key="`${graphId}:${group.id}`" :graph-id="graphId" :group-id="group.id" :members="group.members" :ready="ready" @sent="onSent" /></ConversationComposerDock>
  </ConversationWindow>
</template>

<style scoped src="./groupBoard.css"></style>
