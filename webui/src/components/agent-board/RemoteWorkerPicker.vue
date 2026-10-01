<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listRemoteWorkers, type RegisteredRemoteWorker } from '../../remoteWorkerApi'
import { listRemoteWorkerDirectories } from '../../api'
import WebFolderPickerDialog from '../WebFolderPickerDialog.vue'

const props = defineProps<{ workerId?: string; workingPath?: string }>()
const emit = defineEmits<{
  close: []
  disconnect: []
  select: [worker: RegisteredRemoteWorker, workingPath: string]
}>()
const workers = ref<RegisteredRemoteWorker[]>([])
const selected = ref('')
const path = ref(props.workingPath || '')
const loading = ref(false)
const error = ref('')
const folderOpen = ref(false)
function loadDirectory(directory: string) {
  return listRemoteWorkerDirectories(selected.value, directory)
}
function selectDirectory(directory: string) {
  path.value = directory
  folderOpen.value = false
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    workers.value = await listRemoteWorkers()
    if (!selected.value && props.workerId) selected.value = props.workerId
  } catch (cause) {
    error.value = String(cause)
  } finally { loading.value = false }
}
function choose(worker: RegisteredRemoteWorker) {
  selected.value = worker.worker_id
  path.value = worker.worker_id === props.workerId && props.workingPath
    ? props.workingPath : worker.workspace_path
}
function confirm() {
  const worker = workers.value.find(item => item.worker_id === selected.value)
  if (worker?.online && path.value.trim()) emit('select', worker, path.value.trim())
}
onMounted(load)
</script>

<template>
  <Teleport to="body">
    <div class="remote-picker-overlay" @click.self="emit('close')" @keydown.esc="emit('close')">
      <section class="remote-picker modal" role="dialog" aria-modal="true" aria-labelledby="remote-picker-title">
        <header><strong id="remote-picker-title">LinkToRemote · 选择远程执行设备</strong><button @click="emit('close')">关闭</button></header>
        <p>选择登记到当前 AgentPark，或同一鉴权中心下的远程设备。</p>
        <p v-if="error" role="alert">{{ error }}</p>
        <p v-if="loading">正在加载设备…</p>
        <p v-else-if="!workers.length">暂无可用设备。请让远端 AgentPark 或 Remote 接入同一鉴权中心并通过审核。</p>
        <div class="remote-picker-list">
          <button v-for="worker in workers" :key="worker.worker_id" class="remote-option"
            :class="{ selected: selected === worker.worker_id }" :disabled="!worker.online" @click="choose(worker)">
            <strong>{{ worker.display_name }}</strong>
            <span>{{ worker.online ? '在线' : '离线' }} · {{ worker.host_kind === 'runtime' ? 'AgentPark 运行时' : 'Remote 执行端' }} · {{ worker.connection_kind === 'direct' ? '当前 AgentPark' : '鉴权中心设备' }}</span>
            <span>{{ worker.workspace_path }}</span>
          </button>
        </div>
        <label>此节点的远程工作目录<input v-model="path" placeholder="填写远端机器上的绝对目录"></label>
        <button :disabled="!selected" @click="folderOpen = true">浏览远程目录</button>
        <p v-if="workerId">断开连接会解除此节点的远程绑定，并清空工作目录。</p>
        <footer><button :disabled="loading" @click="load">刷新</button>
          <button v-if="workerId" class="disconnect" @click="emit('disconnect')">断开连接</button>
          <button :disabled="!path.trim() || !workers.some(w => w.worker_id === selected && w.online)" @click="confirm">连接此设备</button></footer>
      </section>
    </div>
  </Teleport>
  <WebFolderPickerDialog :open="folderOpen" :initial-path="path" title="选择远程工作目录"
    :directory-loader="loadDirectory" @close="folderOpen = false" @select="selectDirectory" />
</template>

<style scoped>
.remote-picker-overlay { position: fixed; inset: 0; z-index: 12000; background: #0008; display: grid; place-items: center; padding: 20px; }
.remote-picker { width: min(620px, 100%); max-height: 85vh; overflow: auto; background: var(--theme-panel-background-color, #17202e); color: var(--theme-panel-text, #edf2f7); border: 1px solid #8895; border-radius: 12px; padding: 20px; display: grid; gap: 16px; }
header, footer { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
header > button { flex-shrink: 0; white-space: nowrap; }
footer { flex-wrap: wrap; }
.disconnect { color: #ffb4a9; border-color: #ffb4a980; }
p { margin: 0; } .remote-picker-list { display: grid; gap: 8px; }
button, input { border: 1px solid #8898; border-radius: 6px; padding: 9px 12px; background: transparent; color: inherit; }
button { cursor: pointer; } button:disabled { opacity: .45; cursor: default; }
.remote-option { display: grid; gap: 6px; text-align: left; overflow-wrap: anywhere; }
.remote-option.selected { border-color: #63b3ed; background: #63b3ed20; }
.remote-option span { font-size: 12px; opacity: .8; }
label { display: grid; gap: 8px; } [role=alert] { color: #ff9b9b; }
</style>
