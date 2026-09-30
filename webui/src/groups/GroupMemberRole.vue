<script setup lang="ts">
import { ref } from 'vue'
import { groupApi, type GroupMember } from './groupApi'

const props = defineProps<{ graphId: string; groupId: string; member: GroupMember }>()
const emit = defineEmits<{ updated: [] }>()
const editing = ref(false)
const role = ref('')
const expectedRole = ref('')
const saving = ref(false)
const error = ref('')

function begin() {
  role.value = props.member.role
  expectedRole.value = props.member.role
  error.value = ''
  editing.value = true
}

async function save() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  try {
    await groupApi.updateRole(props.graphId, props.groupId, props.member.node_id, {
      expected_role: expectedRole.value, role: role.value,
    })
    editing.value = false
    emit('updated')
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally { saving.value = false }
}
</script>

<template>
  <div class="member-role">
    <template v-if="!editing"><p>{{ member.role || '未设角色' }}</p><button @click="begin">编辑角色</button></template>
    <form v-else @submit.prevent="save">
      <label>职责与分工<textarea v-model="role" rows="3" maxlength="2000" :aria-label="`${member.node_id} 的角色`" /></label>
      <p v-if="error" role="alert">{{ error }}</p>
      <div><button type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存角色' }}</button><button type="button" :disabled="saving" @click="editing = false">取消</button></div>
    </form>
  </div>
</template>

<style scoped>
.member-role { margin-top: 6px; font-size: 12px; }
p { margin: 0 0 6px; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text-secondary); line-height: 1.5; }
form, label { display: grid; gap: 6px; }
textarea { box-sizing: border-box; width: 100%; resize: vertical; padding: 8px; font: inherit; background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border-medium); border-radius: 8px; }
form > div { display: flex; gap: 6px; }
button { min-height: 32px; padding: 4px 8px; cursor: pointer; }
[role='alert'] { color: var(--accent-red); }
</style>
