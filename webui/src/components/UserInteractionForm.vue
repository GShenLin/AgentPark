<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { getActiveApiBase, type UserInteractionRequest } from '../api'
import { uploadFiles } from '../uploadApi'
import { getInteractionDraft, saveInteractionDraft, validateInteractionDraft, type InteractionDraft } from '../interactionFormState'
import ActionButton from './ActionButton.vue'
import UserInteractionField from './UserInteractionField.vue'

const props = defineProps<{ request: UserInteractionRequest; submitting?: boolean; error?: string }>()
const emit = defineEmits<{
  submit: [response: Record<string, unknown>, requestId: string]
  cancel: [requestId: string]
  error: [message: string]
}>()
const draft = ref<InteractionDraft | null>(null)
const fieldErrors = ref<Record<string, string>>({})
const uploading = ref(false)
const draftError = ref('')
const scope = getActiveApiBase()
const fields = computed(() => props.request.schema.fields)
const busy = computed(() => props.submitting || uploading.value)

watch(() => props.request.id, () => {
  fieldErrors.value = {}
  draftError.value = ''
  try { draft.value = reactive(getInteractionDraft(props.request, scope, localStorage)) }
  catch (error) { draft.value = null; draftError.value = String(error) }
}, { immediate: true })

watch(draft, value => {
  if (!value) return
  try { saveInteractionDraft(props.request.id, scope, value, localStorage); draftError.value = '' }
  catch (error) { draftError.value = `草稿保存失败：${String(error)}` }
}, { deep: true, flush: 'sync' })

function selectFiles(id: string, files: File[]) {
  if (!draft.value) return
  draft.value.uploaded[id] = []
  draft.value.selectedFiles[id] = files
}

async function submitForm() {
  if (busy.value || !draft.value || props.request.status !== 'pending') return
  const request = props.request, current = draft.value
  fieldErrors.value = validateInteractionDraft(request.schema.fields, current)
  if (Object.keys(fieldErrors.value).length) return
  uploading.value = true
  try {
    for (const field of request.schema.fields) {
      if (field.type !== 'file' || !current.selectedFiles[field.id]?.length) continue
      const result = await uploadFiles(current.selectedFiles[field.id]!, `interaction-${request.id}-${field.id}`)
      current.uploaded[field.id] = result.files
      current.selectedFiles[field.id] = []
    }
    saveInteractionDraft(request.id, scope, current, localStorage)
    emit('submit', { values: { ...current.values }, files: { ...current.uploaded } }, request.id)
    await nextTick()
  } catch (error) { emit('error', error instanceof Error ? error.message : String(error)) }
  finally { uploading.value = false }
}
</script>

<template>
  <form class="interaction-form" novalidate @submit.prevent="submitForm">
    <div class="interaction-agent">
      <span v-if="request.agent?.node_name || request.agent?.node_id">{{ request.agent.node_name || request.agent.node_id }}</span>
      <span v-if="request.agent?.graph_id">{{ request.agent.graph_id }}</span>
    </div>
    <p v-if="request.schema.description" class="interaction-description">{{ request.schema.description }}</p>
    <div v-if="request.desktop?.status === 'failed'" class="interaction-error" role="alert">独立窗口未能打开：{{ request.desktop.error }}</div>
    <fieldset v-if="draft" class="interaction-fields" :disabled="busy || request.status !== 'pending'">
      <UserInteractionField v-for="field in fields" :key="`${request.id}:${field.id}`" :field="field" :value="draft.values[field.id]"
        :error="fieldErrors[field.id]" :files="[...(draft.uploaded[field.id] || []), ...(draft.selectedFiles[field.id] || [])].map(file => file.name)"
        @value="draft.values[field.id] = $event; delete fieldErrors[field.id]" @files="selectFiles(field.id, $event)" />
    </fieldset>
    <div v-if="error || draftError" class="interaction-error" role="alert">{{ error || draftError }}</div>
    <footer class="interaction-actions">
      <ActionButton :disabled="busy" @click="emit('cancel', request.id)">取消请求</ActionButton>
      <ActionButton type="submit" variant="primary" :disabled="busy || !draft || request.status !== 'pending'">
        {{ uploading ? '正在准备提交…' : submitting ? '正在提交…' : request.schema.confirm_label }}
      </ActionButton>
    </footer>
  </form>
</template>

<style scoped>
.interaction-form { display: flex; flex-direction: column; min-height: 0; gap: 14px; }
.interaction-agent { display: flex; flex-wrap: wrap; gap: 6px; font-size: 12px; color: var(--text-secondary); }
.interaction-agent span { border: 1px solid var(--ui-dialog-border); padding: 3px 8px; border-radius: 6px; }
.interaction-description { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; }
.interaction-fields { display: grid; gap: 18px; border: 0; padding: 0; margin: 0; min-width: 0; }
.interaction-actions { display: flex; justify-content: flex-end; gap: 8px; padding-top: 12px; border-top: 1px solid var(--ui-dialog-border); }
.interaction-error, :deep(.interaction-field-error) { color: var(--text-danger, #ef7070); overflow-wrap: anywhere; }
:deep(.interaction-field) { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
:deep(.interaction-field small) { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.5; }
:deep(.interaction-label) { display: flex; align-items: baseline; gap: 8px; font-weight: 600; }
:deep(.interaction-required) { font-size: 11px; font-weight: 400; color: var(--text-secondary); }
:deep(.interaction-options) { display: flex; flex-wrap: wrap; gap: 8px; }
:deep(.interaction-options button) { padding: 7px 12px; color: inherit; background: var(--ui-control-background); border: 1px solid var(--ui-control-border); border-radius: 7px; }
:deep(.interaction-options button.selected) { border-color: var(--ui-primary-border, #3b82f6); background: var(--ui-primary-background); }
:deep(.interaction-options button:disabled) { opacity: .5; }
</style>
