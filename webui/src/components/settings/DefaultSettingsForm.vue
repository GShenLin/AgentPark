<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'
import PasteAgentProfileSettingsGroup from './PasteAgentProfileSettingsGroup.vue'
import StorageSettingsGroup from './StorageSettingsGroup.vue'
import { t } from '../../i18n'
import type { LongTermMemorySettings } from '../../longTermMemorySettings'
import LongTermMemorySettingsGroup from './LongTermMemorySettingsGroup.vue'
import ConversationContextSettingsGroup from './ConversationContextSettingsGroup.vue'
import type { ConversationContextSettings } from '../../conversationContextSettings'
import { DEFAULT_AGENT_PANEL_SETTINGS } from '../../agentPanelSettings'

const props = defineProps<{
  data: Record<string, unknown>
  memoryDefaults?: LongTermMemorySettings
  conversationDefaults?: ConversationContextSettings
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
      <h2>{{ t('defaults.agentPanel') }}</h2>
      <div class="form-grid">
        <label v-for="dimension in (['width', 'height'] as const)" :key="dimension">
          <span>{{ t(dimension === 'width' ? 'defaults.agentPanelWidth' : 'defaults.agentPanelHeight') }}</span>
          <FormTextInput
            :model-value="fieldText('agentPanel', dimension)"
            :placeholder="String(DEFAULT_AGENT_PANEL_SETTINGS[dimension])"
            type="number"
            :min="dimension === 'width' ? 360 : 320"
            max="7680"
            step="1"
            @update:model-value="setNestedNumber('agentPanel', dimension, $event)"
          />
          <small>{{ t('defaults.agentPanelSizeHelp') }}</small>
        </label>
      </div>
    </section>

    <ConversationContextSettingsGroup
      :data="section('conversationContext')" :defaults="conversationDefaults"
      @update:data="emit('update:data', { ...props.data, conversationContext: $event })"
    />
    <LongTermMemorySettingsGroup
      :data="section('longTermMemory')" :defaults="memoryDefaults"
      @update:data="emit('update:data', { ...props.data, longTermMemory: $event })"
    />

    <section class="settings-group">
      <h2>{{ t('defaults.boardLayout') }}</h2>
      <div class="form-grid">
        <label>
          <span>{{ t('defaults.gridCellWidth') }}</span>
          <FormTextInput
            :model-value="fieldText('boardLayout', 'gridCellWidth') || '300'"
            type="number"
            min="230"
            max="2000"
            @update:model-value="setNestedNumber('boardLayout', 'gridCellWidth', $event)"
          />
        </label>
        <label>
          <span>{{ t('defaults.gridCellHeight') }}</span>
          <FormTextInput
            :model-value="fieldText('boardLayout', 'gridCellHeight') || '320'"
            type="number"
            min="250"
            max="2000"
            @update:model-value="setNestedNumber('boardLayout', 'gridCellHeight', $event)"
          />
        </label>
        <label>
          <span>{{ t('defaults.nodeWidth') }}</span>
          <FormTextInput
            :model-value="fieldText('boardLayout', 'nodeWidth') || '230'"
            type="number"
            min="230"
            max="720"
            @update:model-value="setNestedNumber('boardLayout', 'nodeWidth', $event)"
          />
          <small>{{ t('defaults.nodeWidthHelp') }}</small>
        </label>
        <label>
          <span>{{ t('defaults.nodeHeight') }}</span>
          <FormTextInput
            :model-value="fieldText('boardLayout', 'nodeHeight') || '250'"
            type="number"
            min="250"
            max="760"
            @update:model-value="setNestedNumber('boardLayout', 'nodeHeight', $event)"
          />
          <small>{{ t('defaults.nodeHeightHelp') }}</small>
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>{{ t('defaults.server') }}</h2>
      <div class="form-grid">
        <label>
          <span>{{ t('defaults.host') }}</span>
          <FormTextInput :model-value="fieldText('server', 'host')" @update:model-value="setNestedField('server', 'host', $event)" />
        </label>
        <label>
          <span>{{ t('defaults.port') }}</span>
          <FormTextInput :model-value="fieldText('server', 'port')" type="number" min="1" max="65535" @update:model-value="setNestedNumber('server', 'port', $event)" />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>{{ t('defaults.network') }}</h2>
      <div class="form-grid">
        <label>
          <span>{{ t('defaults.httpProxy') }}</span>
          <FormTextInput
            :model-value="fieldText('network', 'httpProxy')"
            placeholder="http://127.0.0.1:17891"
            @update:model-value="setNestedField('network', 'httpProxy', $event)"
          />
          <small>{{ t('defaults.proxyHelp') }}</small>
        </label>
        <label>
          <span>{{ t('defaults.noProxy') }}</span>
          <FormTextInput
            :model-value="fieldText('network', 'noProxy')"
            placeholder="localhost,127.0.0.1,::1"
            @update:model-value="setNestedField('network', 'noProxy', $event)"
          />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>{{ t('defaults.agentNode') }}</h2>
      <div class="form-grid">
        <label>
          <span>{{ t('defaults.minSendDelay') }}</span>
          <FormTextInput :model-value="fieldText('agentNode', 'minSendDelayMs')" type="number" min="0" @update:model-value="setNestedNumber('agentNode', 'minSendDelayMs', $event)" />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>{{ t('defaults.runtime') }}</h2>
      <div class="form-grid">
        <label>
          <span>{{ t('defaults.consoleTimeout') }}</span>
          <FormTextInput :model-value="fieldText('consoleCommand', 'timeoutSec')" type="number" min="1" @update:model-value="setNestedNumber('consoleCommand', 'timeoutSec', $event)" />
        </label>
        <label>
          <span>{{ t('defaults.memoryEntries') }}</span>
          <FormTextInput :model-value="fieldText('nodeMemory', 'maxEntries')" type="number" min="1" @update:model-value="setNestedNumber('nodeMemory', 'maxEntries', $event)" />
        </label>
      </div>
    </section>

    <section class="settings-group">
      <h2>{{ t('defaults.undo') }}</h2>
      <div class="form-grid">
        <label>
          <span>{{ t('defaults.undoSteps') }}</span>
          <FormTextInput :model-value="fieldText('undo', 'maxSteps') || '5'" type="number" min="0" max="100" @update:model-value="setNestedNumber('undo', 'maxSteps', $event)" />
        </label>
      </div>
    </section>

    <section class="settings-group mcp-group">
      <div class="group-head">
        <h2>{{ t('defaults.mcpServers') }}</h2>
        <div class="mcp-add">
          <FormTextInput v-model="newMcpName" :placeholder="t('defaults.newServer')" @keydown.enter.prevent="addMcpServer" />
          <ActionButton compact @click="addMcpServer">{{ t('common.add') }}</ActionButton>
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
            <DangerButton @click="deleteMcpServer">{{ t('common.delete') }}</DangerButton>
          </div>
          <div class="form-grid">
            <label>
              <span>{{ t('defaults.label') }}</span>
              <FormTextInput :model-value="mcpFieldText('label')" @update:model-value="setMcpField('label', $event)" />
            </label>
            <label>
              <span>{{ t('defaults.transport') }}</span>
              <FormSelect :model-value="mcpFieldText('transport')" @change="setMcpField('transport', $event)">
                <option value="">{{ t('defaults.unset') }}</option>
                <option value="streamable-http">streamable-http</option>
                <option value="stdio">stdio</option>
              </FormSelect>
            </label>
            <label>
              <span>{{ t('defaults.url') }}</span>
              <FormTextInput :model-value="mcpFieldText('url')" @update:model-value="setMcpField('url', $event)" />
            </label>
            <label>
              <span>{{ t('defaults.readTimeout') }}</span>
              <FormTextInput :model-value="mcpFieldText('readTimeoutSeconds')" type="number" min="1" @update:model-value="setMcpNumber('readTimeoutSeconds', $event)" />
            </label>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped src="./DefaultSettingsForm.css"></style>
