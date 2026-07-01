<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  addRemote,
  deleteRemote,
  listRemotes,
  restartServer,
} from '../api'
import type { RemoteEndpoint } from '../apiTypes'

const props = defineProps<{
  activeView: 'board' | 'settings'
  leftCollapsed: boolean
  rightCollapsed: boolean
}>()

const emit = defineEmits<{
  'update:activeView': [value: 'board' | 'settings']
  toggleLeft: []
  toggleRight: []
  error: [message: string]
}>()

const remoteEndpoints = ref<RemoteEndpoint[]>([])
const selectedRemoteId = ref('default')
const showRemoteForm = ref(false)
const remoteFormName = ref('')
const remoteFormHost = ref('')
const remoteFormPort = ref('8788')
const remoteFormPrivate = ref(false)
const isRestarting = ref(false)

const selectedRemote = computed(() => {
  return remoteEndpoints.value.find((remote) => remote.id === selectedRemoteId.value) || remoteEndpoints.value[0] || null
})

const selectedRemoteAddress = computed(() => {
  const remote = selectedRemote.value
  if (!remote) return '127.0.0.1:8788'
  return `${remote.host}:${remote.port}`
})

function remoteBaseUrl(remote: RemoteEndpoint) {
  return `http://${remote.host}:${remote.port}`
}

async function refreshRemotes() {
  remoteEndpoints.value = await listRemotes()
  if (!remoteEndpoints.value.some((remote) => remote.id === selectedRemoteId.value)) {
    selectedRemoteId.value = remoteEndpoints.value[0]?.id || 'default'
  }
}

function selectRemote() {
  const remote = selectedRemote.value
  if (!remote) return
  if (remote.id === 'default') return
  window.open(remoteBaseUrl(remote), '_blank', 'noopener,noreferrer')
}

async function submitRemote() {
  const name = remoteFormName.value.trim()
  const host = remoteFormHost.value.trim()
  const port = remoteFormPort.value.trim()
  if (!name || !host || !port) {
    emit('error', 'Remote name, IP/host, and port are required.')
    return
  }
  try {
    const res = await addRemote({ name, host, port, private: remoteFormPrivate.value })
    remoteEndpoints.value = res.remotes
    showRemoteForm.value = false
    remoteFormName.value = ''
    remoteFormHost.value = ''
    remoteFormPort.value = '8788'
    remoteFormPrivate.value = false
  } catch (e: any) {
    emit('error', String(e?.message || e))
  }
}

async function removeSelectedRemote() {
  const remote = selectedRemote.value
  if (!remote || remote.id === 'default') return
  try {
    const res = await deleteRemote(remote.id)
    remoteEndpoints.value = res.remotes
    selectedRemoteId.value = 'default'
  } catch (e: any) {
    emit('error', String(e?.message || e))
  }
}

async function restartWorkspace() {
  if (isRestarting.value) return
  isRestarting.value = true
  emit('error', '')
  try {
    await restartServer()
  } catch (e: any) {
    emit('error', String(e?.message || e))
    isRestarting.value = false
  }
}

onMounted(async () => {
  try {
    await refreshRemotes()
  } catch (e: any) {
    emit('error', String(e?.message || e))
  }
})
</script>

<template>
  <header class="topbar">
    <div class="brand">AITools Board</div>
    <div class="remote-switcher">
      <span class="remote-label">Remote</span>
      <select v-model="selectedRemoteId" class="remote-select" @change="selectRemote">
        <option v-for="remote in remoteEndpoints" :key="remote.id" :value="remote.id">
          {{ remote.name }} 路 {{ remote.host }}:{{ remote.port }}{{ remote.private ? ' Private' : '' }}
        </option>
      </select>
      <span class="remote-address">{{ selectedRemoteAddress }}</span>
      <button class="topbar-btn" type="button" @click="showRemoteForm = !showRemoteForm">Add</button>
      <button class="topbar-btn danger" type="button" :disabled="selectedRemoteId === 'default'" @click="removeSelectedRemote">Delete</button>
    </div>
    <form v-if="showRemoteForm" class="remote-form" @submit.prevent="submitRemote" @click.stop>
      <input v-model="remoteFormName" class="remote-input" placeholder="Name" />
      <input v-model="remoteFormHost" class="remote-input" placeholder="IP / Host" />
      <input v-model="remoteFormPort" class="remote-input port" placeholder="Port" />
      <label class="remote-private">
        <input v-model="remoteFormPrivate" type="checkbox" />
        <span>Private</span>
      </label>
      <button class="topbar-btn primary" type="submit">Save</button>
    </form>
    <div class="topbar-actions">
      <button v-if="props.activeView === 'board'" class="topbar-btn" type="button" @click="emit('toggleLeft')">
        {{ props.leftCollapsed ? 'Show Files' : 'Hide Files' }}
      </button>
      <button v-if="props.activeView === 'board'" class="topbar-btn" type="button" @click="emit('toggleRight')">
        {{ props.rightCollapsed ? 'Show Memory' : 'Hide Memory' }}
      </button>
      <button class="topbar-btn restart" type="button" :disabled="isRestarting" @click="restartWorkspace">
        {{ isRestarting ? 'Restarting...' : 'Restart' }}
      </button>
      <button
        class="topbar-btn settings"
        type="button"
        :class="{ active: props.activeView === 'settings' }"
        @click="emit('update:activeView', 'settings')"
      >
        Settings
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  position: relative;
  z-index: 2000;
  overflow: visible;
}

/* 远程连接切换器 */
.remote-switcher,
.remote-form {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

/* 远程表单弹窗 */
.remote-form {
  position: absolute;
  left: 360px;
  top: 52px;
  z-index: 30;
  padding: 12px;
  border: 1px solid var(--border-light);
  border-radius: 10px;
  background: rgba(30, 41, 59, 0.98);
  box-shadow: var(--shadow-xl);
  backdrop-filter: blur(20px);
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.remote-label,
.remote-address {
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}

.remote-private {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.remote-private input {
  width: 14px;
  height: 14px;
  accent-color: var(--accent-blue);
}

.remote-select,
.remote-input {
  min-width: 120px;
  max-width: 220px;
  height: 30px;
  border-radius: 6px;
  border: 1px solid var(--border-light);
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 12px;
  padding: 0 10px;
  transition: all var(--transition-fast);
}

.remote-select:hover,
.remote-input:hover {
  border-color: var(--border-medium);
}

.remote-select:focus,
.remote-input:focus {
  outline: 2px solid var(--accent-blue);
  outline-offset: -2px;
  background: var(--bg-secondary);
}

.remote-input.port {
  width: 74px;
  min-width: 74px;
}

/* 按钮区域 */
.topbar-actions {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

/* 顶部按钮基础样式 */
.topbar-btn {
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  padding: 6px 12px;
  border-radius: 6px;
  transition: all var(--transition-fast);
}

.topbar-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: transparent;
  transform: none;
  box-shadow: none;
}

/* 主按钮样式 */
.topbar-btn.primary {
  border-color: var(--accent-blue);
  background: var(--accent-blue-soft);
  color: var(--text-accent);
}

.topbar-btn.primary:hover {
  background: rgba(59, 130, 246, 0.2);
}

/* 危险按钮样式 */
.topbar-btn.danger {
  color: #fca5a5;
}

.topbar-btn.danger:hover {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
}

/* 重启按钮样式 */
.topbar-btn.restart {
  color: #fcd34d;
}

.topbar-btn.restart:hover {
  background: rgba(245, 158, 11, 0.15);
  color: #fcd34d;
}

/* 设置按钮样式 */
.topbar-btn.settings {
  color: var(--text-secondary);
}

.topbar-btn.settings:hover {
  color: var(--text-primary);
}

.topbar-btn.settings.active {
  background: var(--accent-blue-soft);
  border-color: transparent;
  color: var(--text-accent);
}

/* 禁用状态 */
.topbar-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.topbar-btn:disabled:hover {
  background: transparent;
}

/* 响应式适配 */
@media (max-width: 1280px) {
  .topbar-btn {
    padding: 6px 10px;
    font-size: 11px;
  }
}
</style>
