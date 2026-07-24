<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import StorageSettingsGroup from './StorageSettingsGroup.vue'

const props = defineProps<{
  data: Record<string, unknown>
  runtime?: {
    active_memories_root?: string
    configured_memories_root?: string
  }
}>()

const emit = defineEmits<{
  'update:data': [value: Record<string, unknown>]
}>()

const selectedMcpName = ref('')
const newMcpName = ref('')

const mcpServers = computed<Record<string, Record<string, unknown>>>(() => {
  const value = props.data.mcpServers
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, Record<string, unknown>>
    : {}
})

const mcpNames = computed(() => Object.keys(mcpServers.value))
const selectedMcp = computed(() => mcpServers.value[selectedMcpName.value] || null)

watch(
  mcpNames,
  (names) => {
    if (!names.includes(selectedMcpName.value)) {
      selectedMcpName.value = names[0] || ''
    }
  },
  { immediate: true },
)

function cloneData() {
  return JSON.parse(JSON.stringify(props.data || {})) as Record<string, unknown>
}

function section(name: string) {
  const value = props.data[name]
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function fieldText(sectionName: string, key: string) {
  const value = section(sectionName)[key]
  return value === null || value === undefined ? '' : String(value)
}

function setNestedField(sectionName: string, key: string, value: unknown) {
  const next = cloneData()
  const target = {
    ...(next[sectionName] && typeof next[sectionName] === 'object' && !Array.isArray(next[sectionName])
      ? next[sectionName] as Record<string, unknown>
      : {}),
  }
  if (value === '' || value === null || value === undefined) {
    delete target[key]
  } else {
    target[key] = value
  }
  next[sectionName] = target
  emit('update:data', next)
}

function setNestedNumber(sectionName: string, key: string, value: string) {
  const text = String(value || '').trim()
  setNestedField(sectionName, key, text ? Number(text) : '')
}

function mcpFieldText(key: string) {
  const value = selectedMcp.value?.[key]
  return value === null || value === undefined ? '' : String(value)
}

function setMcpField(key: string, value: unknown) {
  const name = selectedMcpName.value
  if (!name || !selectedMcp.value) return
  const next = cloneData()
  const servers = { ...mcpServers.value }
  const server = { ...selectedMcp.value }
  if (value === '' || value === null || value === undefined) {
    delete server[key]
  } else {
    server[key] = value
  }
  servers[name] = server
  next.mcpServers = servers
  emit('update:data', next)
}

function setMcpNumber(key: string, value: string) {
  const text = String(value || '').trim()
  setMcpField(key, text ? Number(text) : '')
}

function addMcpServer() {
  const name = newMcpName.value.trim()
  if (!name || mcpServers.value[name]) return
  const next = cloneData()
  next.mcpServers = {
    ...mcpServers.value,
    [name]: {
      label: name,
      transport: 'streamable-http',
      url: '',
    },
  }
  emit('update:data', next)
  selectedMcpName.value = name
  newMcpName.value = ''
}

function deleteMcpServer() {
  const name = selectedMcpName.value
  if (!name) return
  const next = cloneData()
  const servers = { ...mcpServers.value }
  delete servers[name]
  next.mcpServers = servers
  emit('update:data', next)
  selectedMcpName.value = Object.keys(servers)[0] || ''
}
</script>

<template>
  <div class="defaults-form">
    <StorageSettingsGroup
      :memories-path="fieldText('storage', 'memoriesPath')"
      :runtime="props.runtime"
      @update:memories-path="setNestedField('storage', 'memoriesPath', $event)"
    />

    <section class="settings-group">
      <h2>Server</h2>
      <div class="form-grid">
        <label>
          <span>Host</span>
          <input :value="fieldText('server', 'host')" @input="setNestedField('server', 'host', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>Port</span>
          <input :value="fieldText('server', 'port')" type="number" min="1" max="65535" @input="setNestedNumber('server', 'port', ($event.target as HTMLInputElement).value)" />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>Agent Node</h2>
      <div class="form-grid">
        <label>
          <span>Min Send Delay Ms</span>
          <input :value="fieldText('agentNode', 'minSendDelayMs')" type="number" min="0" @input="setNestedNumber('agentNode', 'minSendDelayMs', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>History Message Limit</span>
          <input :value="fieldText('agentNode', 'historyMessageLimit')" type="number" min="0" @input="setNestedNumber('agentNode', 'historyMessageLimit', ($event.target as HTMLInputElement).value)" />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>Runtime Defaults</h2>
      <div class="form-grid">
        <label>
          <span>Console Timeout Sec</span>
          <input :value="fieldText('consoleCommand', 'timeoutSec')" type="number" min="1" @input="setNestedNumber('consoleCommand', 'timeoutSec', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>Node Memory Max Entries</span>
          <input :value="fieldText('nodeMemory', 'maxEntries')" type="number" min="1" @input="setNestedNumber('nodeMemory', 'maxEntries', ($event.target as HTMLInputElement).value)" />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>Undo</h2>
      <div class="form-grid">
        <label>
          <span>Max Undo Steps</span>
          <input :value="fieldText('undo', 'maxSteps') || '5'" type="number" min="0" max="100" @input="setNestedNumber('undo', 'maxSteps', ($event.target as HTMLInputElement).value)" />
        </label>
      </div>
    </section>

    <section class="settings-group mcp-group">
      <div class="group-head">
        <h2>MCP Servers</h2>
        <div class="mcp-add">
          <input v-model="newMcpName" placeholder="New server name" @keydown.enter.prevent="addMcpServer" />
          <button type="button" @click="addMcpServer">Add</button>
        </div>
      </div>

      <div class="mcp-layout">
        <nav class="mcp-list">
          <button
            v-for="name in mcpNames"
            :key="name"
            type="button"
            class="mcp-item"
            :class="{ active: selectedMcpName === name }"
            @click="selectedMcpName = name"
          >
            <span>{{ name }}</span>
            <small>{{ mcpServers[name]?.url || mcpServers[name]?.transport || '' }}</small>
          </button>
        </nav>

        <div v-if="selectedMcp" class="mcp-fields">
          <div class="form-head">
            <h3>{{ selectedMcpName }}</h3>
            <button type="button" class="danger" @click="deleteMcpServer">Delete</button>
          </div>
          <div class="form-grid">
            <label>
              <span>Label</span>
              <input :value="mcpFieldText('label')" @input="setMcpField('label', ($event.target as HTMLInputElement).value)" />
            </label>
            <label>
              <span>Transport</span>
              <select :value="mcpFieldText('transport')" @change="setMcpField('transport', ($event.target as HTMLSelectElement).value)">
                <option value="">Unset</option>
                <option value="streamable-http">streamable-http</option>
                <option value="stdio">stdio</option>
              </select>
            </label>
            <label>
              <span>URL</span>
              <input :value="mcpFieldText('url')" @input="setMcpField('url', ($event.target as HTMLInputElement).value)" />
            </label>
            <label>
              <span>Read Timeout Seconds</span>
              <input :value="mcpFieldText('readTimeoutSeconds')" type="number" min="1" @input="setMcpNumber('readTimeoutSeconds', ($event.target as HTMLInputElement).value)" />
            </label>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.defaults-form {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-right: 4px;
}

.settings-group {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.28);
}

.settings-group h2,
.form-head h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.group-head,
.form-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 1fr));
  gap: 12px;
}

label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: rgba(226, 232, 240, 0.94);
  font-size: 12px;
}

label small {
  color: rgba(148, 163, 184, 0.9);
  line-height: 1.45;
}

label small.pending-path {
  color: rgba(250, 204, 21, 0.92);
}

input,
select {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  padding: 8px 9px;
  color: rgba(226, 232, 240, 0.96);
  background: rgba(2, 6, 23, 0.5);
  font: inherit;
}

.mcp-add {
  display: flex;
  gap: 6px;
}

.mcp-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 12px;
}

.mcp-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-height: 0;
  max-height: 360px;
  overflow: auto;
}

.mcp-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  text-align: left;
}

.mcp-item.active {
  border-color: rgba(56, 189, 248, 0.66);
  background: rgba(14, 165, 233, 0.18);
}

.mcp-item small {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  color: rgba(148, 163, 184, 0.9);
  font-size: 11px;
}

button.danger {
  border-color: rgba(248, 113, 113, 0.35);
  color: rgba(254, 202, 202, 0.95);
}

@media (max-width: 1120px) {
  .form-grid,
  .mcp-layout {
    grid-template-columns: 1fr;
  }
}
</style>
