<script setup lang="ts">
import { ref } from 'vue'
import { selectRemoteWorkerFolder } from '../../api'
import { pairLocalRemoteWorker } from '../../remoteWorkerConnection'
import ActionButton from '../ActionButton.vue'
import FormCheckbox from '../FormCheckbox.vue'
import FormTextInput from '../FormTextInput.vue'
import WebFolderPickerDialog from '../WebFolderPickerDialog.vue'

const pairingRemote = ref(false)
const localPickerOpen = ref(false)

const props = withDefaults(defineProps<{
  value?: string
  inputAttrs?: Record<string, string | number>
  remoteEnabled?: boolean
  remoteWorkerId?: string
}>(), {
  value: '',
  inputAttrs: () => ({}),
  remoteEnabled: false,
  remoteWorkerId: '',
})

const emit = defineEmits<{
  'update-value': [value: string]
  'update-remote': [value: boolean]
  'update-worker': [value: string]
  error: [message: string]
}>()

async function chooseWorkingPath() {
  if (!props.remoteEnabled) {
    localPickerOpen.value = true
    return
  }
  try {
    const res = await selectRemoteWorkerFolder(String(props.remoteWorkerId || ''), String(props.value ?? ''))
    const selectedPath = String(res?.path || '').trim()
    if (selectedPath) {
      emit('update-value', selectedPath)
    }
  } catch (e: any) {
    emit('error', String(e?.message || e))
  }
}

function selectLocalWorkingPath(path: string) {
  const selectedPath = String(path || '').trim()
  if (!selectedPath) return
  emit('update-value', selectedPath)
  localPickerOpen.value = false
}

async function toggleRemote(checked: boolean) {
  if (pairingRemote.value) return
  if (!checked) {
    emit('update-remote', false)
    emit('update-worker', '')
    return
  }
  try {
    pairingRemote.value = true
    const res = await pairLocalRemoteWorker()
    const worker = res?.worker
    const workerId = String(worker?.worker_id || '').trim()
    if (!workerId) throw new Error('Remote worker pairing returned no worker_id.')
    emit('update-worker', workerId)
    emit('update-remote', true)
    const workspacePath = String(worker?.workspace_path || '').trim()
    if (workspacePath) emit('update-value', workspacePath)
  } catch (e: any) {
    emit('update-remote', false)
    emit('error', String(e?.message || e))
  } finally {
    pairingRemote.value = false
  }
}
</script>

<template>
  <div class="path-picker">
    <FormTextInput
      class="field-input"
      v-bind="inputAttrs"
      :model-value="String(value ?? '')"
      @update:model-value="emit('update-value', $event)"
    />
    <ActionButton icon title="选择工作路径" aria-label="选择工作路径" @click="chooseWorkingPath">…</ActionButton>
    <label class="remote-toggle" title="Pair with the single online AgentPark remote worker on this computer">
      <FormCheckbox :model-value="remoteEnabled" :disabled="pairingRemote" @update:model-value="toggleRemote" />
      <span>{{ pairingRemote ? 'Connecting…' : 'Remote' }}</span>
    </label>
  </div>
  <WebFolderPickerDialog
    :open="localPickerOpen"
    :initial-path="String(value ?? '')"
    title="选择节点工作路径"
    @close="localPickerOpen = false"
    @select="selectLocalWorkingPath"
    @error="emit('error', $event)"
  />
</template>

<style scoped>
.path-picker {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 34px auto;
  gap: 6px;
  align-items: center;
}

.remote-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--theme-panel-node-side-editor-input-text, #f8fafc);
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
}

</style>
