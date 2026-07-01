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
    const res = await addRemote({ name, host, port })
    remoteEndpoints.value = res.remotes
    showRemoteForm.value = false
    remoteFormName.value = ''
    remoteFormHost.value = ''
    remoteFormPort.value = '8788'
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
    <div class="brand">AgentPark Board</div>
    <div class="remote-switcher">
      <span class="remote-label">Remote</span>
      <select v-model="selectedRemoteId" class="remote-select" @change="selectRemote">
        <option v-for="remote in remoteEndpoints" :key="remote.id" :value="remote.id">
          {{ remote.name }} 路 {{ remote.host }}:{{ remote.port }}
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

.remote-switcher,
.remote-form {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.remote-form {
  position: absolute;
  left: 360px;
  top: 48px;
  z-index: 30;
  padding: 8px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(2, 6, 23, 0.94);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.28);
}

.remote-label,
.remote-address {
  color: rgba(148, 163, 184, 0.88);
  font-size: 11px;
  white-space: nowrap;
}

.remote-select,
.remote-input {
  min-width: 120px;
  max-width: 220px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: rgba(15, 23, 42, 0.7);
  color: rgba(226, 232, 240, 0.95);
  font-size: 12px;
  padding: 0 9px;
}

.remote-input.port {
  width: 74px;
  min-width: 74px;
}

.topbar-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.topbar-btn {
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.25);
  color: rgba(226, 232, 240, 0.92);
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 8px;
}

.topbar-btn.primary {
  border-color: rgba(56, 189, 248, 0.45);
  color: rgba(186, 230, 253, 0.98);
}

.topbar-btn.danger {
  border-color: rgba(248, 113, 113, 0.35);
  color: rgba(254, 202, 202, 0.95);
}

.topbar-btn.restart {
  border-color: rgba(251, 191, 36, 0.4);
  color: rgba(254, 240, 138, 0.98);
}

.topbar-btn.settings {
  border-color: rgba(56, 189, 248, 0.38);
  color: rgba(186, 230, 253, 0.98);
}

.topbar-btn.settings.active {
  background: rgba(14, 165, 233, 0.2);
  border-color: rgba(56, 189, 248, 0.7);
}

.topbar-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

@media (max-width: 1280px) {
  .topbar-btn {
    padding: 6px 8px;
    font-size: 11px;
  }
}
</style>
