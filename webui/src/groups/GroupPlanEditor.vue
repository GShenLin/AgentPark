<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { groupApi, type AgentGroup } from './groupApi'

const props = defineProps<{ graphId: string; group: AgentGroup }>()
const emit = defineEmits<{ updated: [] }>()
const name = ref(props.group.name)
const objective = ref(props.group.objective)
const base = ref({ name: props.group.name, objective: props.group.objective })
const saving = ref(false)
const error = ref('')
let mounted = true
onBeforeUnmount(() => { mounted = false })
const dirty = computed(() => name.value !== base.value.name || objective.value !== base.value.objective)
const changedElsewhere = computed(() => props.group.name !== base.value.name || props.group.objective !== base.value.objective)

function loadPlan(plan: Pick<AgentGroup, 'name' | 'objective'>) {
  base.value = { name: plan.name, objective: plan.objective }
  name.value = plan.name; objective.value = plan.objective; error.value = ''
}
watch(() => [props.group.name, props.group.objective], () => {
  if (!dirty.value && !saving.value) loadPlan(props.group)
})

async function reload() {
  if (saving.value) return
  saving.value = true; error.value = ''
  try {
    const latest = await groupApi.get(props.graphId, props.group.id)
    if (mounted) { loadPlan(latest); emit('updated') }
  } catch (reason) {
    if (mounted) error.value = reason instanceof Error ? reason.message : String(reason)
  } finally { saving.value = false }
}

async function save() {
  if (saving.value || !dirty.value) return
  saving.value = true; error.value = ''
  try {
    const saved = await groupApi.updatePlan(props.graphId, props.group.id, {
      expected_name: base.value.name, expected_objective: base.value.objective,
      name: name.value, objective: objective.value,
    })
    if (mounted) { loadPlan(saved); emit('updated') }
  } catch (reason) {
    if (mounted) error.value = reason instanceof Error ? reason.message : String(reason)
  } finally { saving.value = false }
}
</script>

<template>
  <details class="group-plan">
    <summary>计划与目标</summary>
    <form @submit.prevent="save">
      <label>组名称<input v-model="name" :disabled="saving" required maxlength="240" /></label>
      <label>目标<textarea v-model="objective" :disabled="saving" rows="3" maxlength="32000" /></label>
      <p v-if="changedElsewhere" role="status">计划已有更新。当前草稿已保留，保存不会覆盖其他人的修改。</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <div><button type="submit" :disabled="saving || !dirty">{{ saving ? '保存中…' : '保存计划' }}</button>
        <button v-if="dirty || changedElsewhere || error" type="button" :disabled="saving" @click="reload">放弃草稿并载入最新计划</button></div>
    </form>
  </details>
</template>

<style scoped>
summary { cursor: pointer; font-weight: 600; }
form, label { display: grid; gap: 8px; }
form { margin-top: 10px; gap: 12px; }
label, p { font-size: 13px; }
p { margin: 0; line-height: 1.6; color: var(--text-secondary); }
[role='alert'] { color: var(--accent-red); }
input, textarea { box-sizing: border-box; width: 100%; padding: 9px 12px; border: 1px solid var(--border-medium); border-radius: 10px; background: var(--bg-primary); color: var(--text-primary); font: inherit; }
textarea { resize: vertical; }
form > div { display: flex; flex-wrap: wrap; gap: 8px; }
button { cursor: pointer; min-height: 32px; padding: 6px 12px; }
</style>
