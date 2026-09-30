<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { groupApi, type AgentGroup, type GroupDelivery, type GroupEvent, type GroupTask } from './groupApi'
import { taskDelivery, taskFeedback } from './taskFeedback'
import GroupTaskItem from './GroupTaskItem.vue'

const props = defineProps<{ graphId: string; group: AgentGroup; events: GroupEvent[]; deliveries: GroupDelivery[];
  nodeConfigs: Record<string, { state?: string }>; ready: boolean }>()
const emit = defineEmits<{ updated: [] }>()
const title = ref(''), error = ref(''), adding = ref(false)
const savedTask = ref<GroupTask | null>(null)
const active = computed(() => props.group.tasks.filter(task => task.status !== 'done'))
const archived = computed(() => props.group.tasks.filter(task => task.status === 'done').sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
const feedback = computed(() => {
  const saved = savedTask.value
  const current = props.group.tasks.find(task => task.id === saved?.id)
  const task = current && saved && current.revision >= saved.revision ? current : saved
  return task ? readiness(task) : ''
})
let mounted = true
onBeforeUnmount(() => { mounted = false })
function readiness(task: GroupTask) {
  return taskFeedback(task, props.group.tasks, taskDelivery(task, props.events, props.deliveries),
    task.owner_id ? props.nodeConfigs[task.owner_id]?.state : undefined)
}
function saved(task: GroupTask) { savedTask.value = task; emit('updated') }
async function add() {
  if (!title.value.trim() || adding.value || !props.ready) return
  adding.value = true; error.value = ''
  try {
    const task = await groupApi.createTask(props.graphId, props.group.id, { title: title.value.trim() })
    if (mounted) { title.value = ''; saved(task) }
  } catch (reason) { if (mounted) error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { adding.value = false }
}
</script>

<template>
  <section class="group-task-list">
    <header class="group-task-heading"><h3>任务 <span>{{ active.length }}</span></h3></header>
    <form class="group-task-create" @submit.prevent="add"><input v-model="title" placeholder="添加一个任务" aria-label="新任务标题" maxlength="240" /><button :disabled="!title.trim() || adding || !ready">{{ adding ? '添加中…' : '添加' }}</button></form>
    <p v-if="error" class="group-error" role="alert">{{ error }}</p>
    <p v-if="feedback" class="group-task-save-feedback" role="status">{{ feedback }}</p>
    <p v-if="!active.length" class="group-muted">暂无未完成任务。可以添加任务并指定负责人。</p>
    <div class="group-active-tasks">
      <GroupTaskItem v-for="task in active" :key="task.id" :graph-id="graphId" :group="group" :task="task" :feedback="readiness(task)" :ready="ready" @saved="saved" />
    </div>
    <details class="group-task-archive">
      <summary>归档任务 <span>{{ archived.length }}</span></summary>
      <p class="group-muted">已完成任务自动收拢于此，保留说明、负责人和完成证据。重新打开的任务会回到上方。</p>
      <p v-if="!archived.length" class="group-muted">暂无已完成任务</p>
      <GroupTaskItem v-for="task in archived" :key="task.id" :graph-id="graphId" :group="group" :task="task" :feedback="readiness(task)" :ready="ready" @saved="saved" />
    </details>
  </section>
</template>

<style scoped src="./groupTasks.css"></style>
