<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'
import PasteAgentProfileSettingsGroup from './PasteAgentProfileSettingsGroup.vue'
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

    <PasteAgentProfileSettingsGroup />

    <section class="settings-group">
      <h2>Board Layout</h2>
      <div class="form-grid">
        <label>
          <span>Grid Cell Width</span>
          <FormTextInput
            :model-value="fieldText('boardLayout', 'gridCellWidth') || '300'"
            type="number"
            min="230"
            max="2000"
            @update:model-value="setNestedNumber('boardLayout', 'gridCellWidth', $event)"
          />
        </label>
        <label>
          <span>Grid Cell Height</span>
          <FormTextInput
            :model-value="fieldText('boardLayout', 'gridCellHeight') || '320'"
            type="number"
            min="250"
            max="2000"
            @update:model-value="setNestedNumber('boardLayout', 'gridCellHeight', $event)"
          />
        </label>
        <label>
          <span>Default Node Width</span>
          <FormTextInput
            :model-value="fieldText('boardLayout', 'nodeWidth') || '230'"
            type="number"
            min="230"
            max="720"
            @update:model-value="setNestedNumber('boardLayout', 'nodeWidth', $event)"
          />
          <small>Applied to newly created nodes. Nodes with saved custom sizes keep their own width.</small>
        </label>
        <label>
          <span>Default Node Height</span>
          <FormTextInput
            :model-value="fieldText('boardLayout', 'nodeHeight') || '250'"
            type="number"
            min="250"
            max="760"
            @update:model-value="setNestedNumber('boardLayout', 'nodeHeight', $event)"
          />
          <small>Applied to newly created nodes. Nodes with saved custom sizes keep their own height.</small>
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>Server</h2>
      <div class="form-grid">
        <label>
          <span>Host</span>
          <FormTextInput :model-value="fieldText('server', 'host')" @update:model-value="setNestedField('server', 'host', $event)" />
        </label>
        <label>
          <span>Port</span>
          <FormTextInput :model-value="fieldText('server', 'port')" type="number" min="1" max="65535" @update:model-value="setNestedNumber('server', 'port', $event)" />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>Network</h2>
      <div class="form-grid">
        <label>
          <span>HTTP Proxy</span>
          <FormTextInput
            :model-value="fieldText('network', 'httpProxy')"
            placeholder="http://127.0.0.1:17891"
            @update:model-value="setNestedField('network', 'httpProxy', $event)"
          />
          <small>Applied to AgentPark at startup and inherited by processes it launches.</small>
        </label>
        <label>
          <span>No Proxy</span>
          <FormTextInput
            :model-value="fieldText('network', 'noProxy')"
            placeholder="localhost,127.0.0.1,::1"
            @update:model-value="setNestedField('network', 'noProxy', $event)"
          />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>Agent Node</h2>
      <div class="form-grid">
        <label>
          <span>Min Send Delay Ms</span>
          <FormTextInput :model-value="fieldText('agentNode', 'minSendDelayMs')" type="number" min="0" @update:model-value="setNestedNumber('agentNode', 'minSendDelayMs', $event)" />
        </label>
        <label>
          <span>History Message Limit</span>
          <FormTextInput :model-value="fieldText('agentNode', 'historyMessageLimit')" type="number" min="0" @update:model-value="setNestedNumber('agentNode', 'historyMessageLimit', $event)" />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>Runtime Defaults</h2>
      <div class="form-grid">
        <label>
          <span>Console Timeout Sec</span>
          <FormTextInput :model-value="fieldText('consoleCommand', 'timeoutSec')" type="number" min="1" @update:model-value="setNestedNumber('consoleCommand', 'timeoutSec', $event)" />
        </label>
        <label>
          <span>Node Memory Max Entries</span>
          <FormTextInput :model-value="fieldText('nodeMemory', 'maxEntries')" type="number" min="1" @update:model-value="setNestedNumber('nodeMemory', 'maxEntries', $event)" />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>Undo</h2>
      <div class="form-grid">
        <label>
          <span>Max Undo Steps</span>
          <FormTextInput :model-value="fieldText('undo', 'maxSteps') || '5'" type="number" min="0" max="100" @update:model-value="setNestedNumber('undo', 'maxSteps', $event)" />
        </label>
      </div>
    </section>

    <section class="settings-group mcp-group">
      <div class="group-head">
        <h2>MCP Servers</h2>
        <div class="mcp-add">
          <FormTextInput v-model="newMcpName" placeholder="New server name" @keydown.enter.prevent="addMcpServer" />
          <ActionButton compact @click="addMcpServer">Add</ActionButton>
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
            <DangerButton @click="deleteMcpServer">Delete</DangerButton>
          </div>
          <div class="form-grid">
            <label>
              <span>Label</span>
              <FormTextInput :model-value="mcpFieldText('label')" @update:model-value="setMcpField('label', $event)" />
            </label>
            <label>
              <span>Transport</span>
              <FormSelect :model-value="mcpFieldText('transport')" @change="setMcpField('transport', $event)">
                <option value="">Unset</option>
                <option value="streamable-http">streamable-http</option>
                <option value="stdio">stdio</option>
              </FormSelect>
            </label>
            <label>
              <span>URL</span>
              <FormTextInput :model-value="mcpFieldText('url')" @update:model-value="setMcpField('url', $event)" />
            </label>
            <label>
              <span>Read Timeout Seconds</span>
              <FormTextInput :model-value="mcpFieldText('readTimeoutSeconds')" type="number" min="1" @update:model-value="setMcpNumber('readTimeoutSeconds', $event)" />
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

@media (max-width: 1120px) {
  .form-grid,
  .mcp-layout {
    grid-template-columns: 1fr;
  }
}
</style>
