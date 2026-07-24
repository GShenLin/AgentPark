<script setup lang="ts">
import { ref } from 'vue'
import { discoverLocalRemoteWorker, pairRemoteWorker, selectRemoteWorkerFolder } from '../../api'
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

async function toggleRemote(event: Event) {
  if (pairingRemote.value) return
  const checked = (event.target as HTMLInputElement).checked
  if (!checked) {
    emit('update-remote', false)
    emit('update-worker', '')
    return
  }
  try {
    pairingRemote.value = true
    await discoverLocalRemoteWorker()
    let res: Awaited<ReturnType<typeof pairRemoteWorker>> | undefined
    let lastError: unknown
    for (let attempt = 0; attempt < 24; attempt += 1) {
      try {
        res = await pairRemoteWorker()
        break
      } catch (error: any) {
        lastError = error
        if (!String(error?.message || error).includes('HTTP 404')) throw error
        await new Promise(resolve => window.setTimeout(resolve, 250))
      }
    }
    if (!res) throw lastError || new Error('Remote worker did not register with AgentPark in time.')
    const worker = res?.worker
    const workerId = String(worker?.worker_id || '').trim()
    if (!workerId) throw new Error('Remote worker pairing returned no worker_id.')
    emit('update-worker', workerId)
    emit('update-remote', true)
    const workspacePath = String(worker?.workspace_path || '').trim()
    if (workspacePath) emit('update-value', workspacePath)
  } catch (e: any) {
    ;(event.target as HTMLInputElement).checked = false
    emit('error', String(e?.message || e))
  } finally {
    pairingRemote.value = false
  }
}
</script>

<template>
  <div class="path-picker">
    <input
      class="field-input"
      type="text"
      v-bind="inputAttrs"
      :value="String(value ?? '')"
      @input="emit('update-value', ($event.target as HTMLInputElement).value)"
    />
    <button class="path-picker-btn" type="button" title="选择工作路径" @click="chooseWorkingPath">...</button>
    <label class="remote-toggle" title="Pair with the single online AgentPark remote worker on this computer">
      <input type="checkbox" :checked="remoteEnabled" :disabled="pairingRemote" @change="toggleRemote" />
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

.field-input {
  width: 100%;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.22));
  border-radius: 10px;
  background: var(--theme-panel-node-side-editor-input-background, rgba(15, 23, 42, 0.88));
  color: var(--theme-panel-node-side-editor-input-text, #f8fafc);
  padding: 10px 12px;
  font-size: var(--theme-panel-node-side-editor-input-font-size, 13px);
  outline: none;
}

.field-input:focus {
  border-color: var(--theme-panel-node-side-editor-input-focus-border, rgba(56, 189, 248, 0.7));
}

.path-picker-btn {
  height: 36px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.88);
  color: #f8fafc;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}

.path-picker-btn:hover {
  border-color: rgba(56, 189, 248, 0.7);
}
</style>
