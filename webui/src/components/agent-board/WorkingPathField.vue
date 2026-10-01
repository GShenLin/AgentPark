<script setup lang="ts">
import { ref } from 'vue'
import { listRemoteWorkerDirectories } from '../../api'
import RemoteWorkerPicker from './RemoteWorkerPicker.vue'
import type { RegisteredRemoteWorker } from '../../remoteWorkerApi'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import WebFolderPickerDialog from '../WebFolderPickerDialog.vue'

const remotePickerOpen = ref(false)
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

function chooseWorkingPath() {
  localPickerOpen.value = true
}

function loadRemoteDirectory(path: string) {
  return listRemoteWorkerDirectories(props.remoteWorkerId, path)
}

function selectLocalWorkingPath(path: string) {
  const selectedPath = String(path || '').trim()
  if (!selectedPath) return
  emit('update-value', selectedPath)
  localPickerOpen.value = false
}

function selectRemote(worker: RegisteredRemoteWorker, path: string) {
  emit('update-worker', worker.worker_id)
  emit('update-remote', true)
  emit('update-value', path)
  remotePickerOpen.value = false
}

function disconnectRemote() {
  emit('update-worker', '')
  emit('update-remote', false)
  emit('update-value', '')
  remotePickerOpen.value = false
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
    <button class="remote-toggle" :title="remoteWorkerId" @click="remotePickerOpen = true">{{ remoteEnabled ? 'Remote · 更换设备' : 'LinkToRemote' }}</button>
  </div>
  <WebFolderPickerDialog
    :open="localPickerOpen"
    :initial-path="String(value ?? '')"
    :title="remoteEnabled ? '选择远程工作目录' : '选择节点工作路径'"
    :directory-loader="remoteEnabled ? loadRemoteDirectory : undefined"
    @close="localPickerOpen = false"
    @select="selectLocalWorkingPath"
    @error="emit('error', $event)"
  />
  <RemoteWorkerPicker v-if="remotePickerOpen" :worker-id="remoteWorkerId" :working-path="value"
    @close="remotePickerOpen = false" @select="selectRemote" @disconnect="disconnectRemote" />
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
