<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { groupApi, type AgentGroup, type GroupTask, type TaskStatus } from './groupApi'

const props = defineProps<{ graphId: string; group: AgentGroup; task: GroupTask; feedback: string; ready: boolean }>()
const emit = defineEmits<{ saved: [task: GroupTask] }>()
const draft = ref<GroupTask | null>(null)
const saving = ref(false)
const error = ref('')
const labels: Record<TaskStatus, string> = { todo: '待处理', in_progress: '进行中', blocked: '受阻', done: '完成' }
let mounted = true
onBeforeUnmount(() => { mounted = false })
function toggle() {
  if (saving.value) return
  error.value = ''
  draft.value = draft.value ? null : { ...props.task, dependencies: [...props.task.dependencies] }
}
async function save() {
  const task = draft.value
  if (!task || saving.value || !props.ready) return
  saving.value = true; error.value = ''
  try {
    const saved = await groupApi.updateTask(props.graphId, props.group.id, task.id, {
      expected_revision: task.revision, title: task.title, description: task.description,
      status: task.status, owner_id: task.owner_id, evidence: task.evidence, dependencies: task.dependencies,
    })
    if (mounted) { draft.value = null; emit('saved', saved) }
  } catch (reason) { if (mounted) error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { saving.value = false }
}
</script>

<template>
  <article class="group-task-item" :data-task-id="task.id">
    <button class="group-task" :aria-expanded="!!draft" :aria-controls="`task-editor-${task.id}`" @click="toggle">
      <span class="group-task-status" :data-status="task.status">{{ labels[task.status] }}</span>
      <strong>{{ task.title }}</strong><span class="group-task-owner">{{ task.owner_id || '未认领' }}</span>
      <span class="group-task-feedback">{{ feedback }}</span>
    </button>
    <form v-if="draft" :id="`task-editor-${task.id}`" class="group-task-editor" @submit.prevent="save">
      <fieldset :disabled="saving || !ready">
        <label>标题<input v-model="draft.title" required maxlength="240" /></label>
        <label>说明<textarea v-model="draft.description" rows="3" /></label>
        <label>负责人<select v-model="draft.owner_id"><option :value="null">未认领</option><option v-for="member in group.members" :key="member.node_id" :value="member.node_id">{{ member.node_id }}</option></select></label>
        <label>状态<select v-model="draft.status"><option v-for="(label, status) in labels" :key="status" :value="status">{{ label }}</option></select></label>
        <label>前置任务（全部完成后就绪，可多选）<select v-model="draft.dependencies" multiple><option v-for="dependency in group.tasks.filter(item => item.id !== task.id)" :key="dependency.id" :value="dependency.id">{{ dependency.title }} · {{ labels[dependency.status] }}</option></select></label>
        <label>完成证据 / 验证记录<textarea v-model="draft.evidence" rows="4" /></label>
        <p v-if="task.revision !== draft.revision" role="status">任务已有更新，当前草稿已保留。请取消并重新展开以查看最新内容。</p>
        <p v-if="error" class="group-error" role="alert">{{ error }}</p>
        <div class="group-task-actions"><button type="submit">{{ saving ? '保存中…' : '保存任务' }}</button><button type="button" @click="draft = null">取消</button></div>
      </fieldset>
    </form>
  </article>
</template>

<style scoped src="./groupTasks.css"></style>
