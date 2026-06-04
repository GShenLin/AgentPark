<script setup lang="ts">
import { computed } from 'vue'
import type { ProviderInfo } from '../../api'
import { ASSET_FIELD_KEYS } from '../../composables/droppedPaths'
import {
  dedupeStrings,
  GUI_AGENT_MODE,
  GUI_AGENT_NODE_TYPE,
  IMAGE_GENERATION_MODE,
  IMAGE_GENERATION_NODE_TYPE,
  normalizeMode,
  normalizeSwitch,
  normalizeToolSelection,
  providerModes,
  switchOptions,
  VIDEO_GENERATION_MODE,
  VIDEO_GENERATION_NODE_TYPE,
} from '../../composables/useAgentNodeCreateSchema'
import {
  getSchemaFieldHint,
  getSchemaFieldLabel,
  getSchemaFieldOptions,
  getSchemaFieldText,
  getSchemaFieldType,
  getSchemaInputAttrs,
  getSchemaInputType,
  isSchemaBooleanValue,
  isSchemaSelectField,
} from '../../composables/nodeSchemaFields'
import WorkingPathField from './WorkingPathField.vue'

type NodeFields = Record<string, any>

const props = withDefaults(defineProps<{
  typeId: string
  schema: Record<string, any>
  fields: NodeFields
  providers: ProviderInfo[]
  availableTools: string[]
  dropTargetKey?: string
  uploadingKey?: string
  enableAssetDrop?: boolean
}>(), {
  dropTargetKey: '',
  uploadingKey: '',
  enableAssetDrop: false,
})

const emit = defineEmits<{
  'update-field': [key: string, value: any]
  'field-dragover': [key: string, event: DragEvent]
  'field-dragleave': [key: string, event: DragEvent]
  'field-drop': [key: string, event: DragEvent]
  'field-error': [message: string]
}>()

const defaultModeOrder = ['chat', 'image_generation', 'video_generation', 'imagechat', 'vision_understand']
const schemaKeys = computed(() => Object.keys(props.schema || {}))
const modeOptions = computed(() => {
  const discovered = props.providers.flatMap((provider) => providerModes(provider))
  const merged = dedupeStrings([...defaultModeOrder, ...discovered].map((mode) => normalizeMode(mode)))
  return merged.length ? merged : ['chat']
})
const toolOptions = computed(() => dedupeStrings(props.availableTools).sort((a, b) => a.localeCompare(b)))
const selectedMode = computed(() => {
  if (props.typeId === GUI_AGENT_NODE_TYPE) return GUI_AGENT_MODE
  if (props.typeId === IMAGE_GENERATION_NODE_TYPE) return IMAGE_GENERATION_MODE
  if (props.typeId === VIDEO_GENERATION_NODE_TYPE) return VIDEO_GENERATION_MODE
  return normalizeMode(props.fields.mode) || modeOptions.value[0] || 'chat'
})
const providerOptions = computed(() => {
  const mode = selectedMode.value
  return dedupeStrings(
    props.providers
      .filter((provider) => providerModes(provider).includes(mode))
      .map((provider) => String(provider.id || '').trim())
      .filter(Boolean),
  ).sort((a, b) => a.localeCompare(b))
})
const toolSelection = computed(() => normalizeToolSelection(props.fields.tools, toolOptions.value))

function setField(key: string, value: any) {
  emit('update-field', key, value)
}

function isModeField(key: string) {
  return props.typeId === 'agent_node' && key === 'mode'
}

function isProviderField(key: string) {
  if (key !== 'provider_id') return false
  return (
    props.typeId === 'agent_node' ||
    props.typeId === GUI_AGENT_NODE_TYPE ||
    props.typeId === IMAGE_GENERATION_NODE_TYPE ||
    props.typeId === VIDEO_GENERATION_NODE_TYPE
  )
}

function isToolsField(key: string) {
  return props.typeId === 'agent_node' && key === 'tools'
}

function isWebSearchField(key: string) {
  return (props.typeId === 'agent_node' || props.typeId === VIDEO_GENERATION_NODE_TYPE) && key === 'web_search'
}

function isThinkingField(key: string) {
  return props.typeId === 'agent_node' && key === 'thinking'
}

function getFieldType(key: string) {
  return getSchemaFieldType(props.schema, key)
}

function getInputType(key: string) {
  return getSchemaInputType(props.schema, key)
}

function isCheckedValue(value: unknown) {
  return isSchemaBooleanValue(value)
}

function getFieldLabel(key: string) {
  return getSchemaFieldLabel(props.schema, key)
}

function getFieldText(key: string) {
  return getSchemaFieldText(props.schema, key, props.fields[key])
}

function getFieldHint(key: string) {
  return getSchemaFieldHint(props.schema, key)
}

function isSelectField(key: string) {
  return isSchemaSelectField(props.schema, key)
}

function getFieldOptions(key: string) {
  return getSchemaFieldOptions(props.schema, key)
}

function getInputAttrs(key: string) {
  return getSchemaInputAttrs(props.schema, key)
}

function isAssetFieldKey(key: string) {
  return ASSET_FIELD_KEYS.has(String(key || '').trim())
}

function isWorkingPathField(key: string) {
  return String(key || '').trim() === 'working_path'
}

function toggleTool(tool: string) {
  const value = String(tool || '').trim()
  if (!value) return
  const current = toolSelection.value
  setField('tools', current.includes(value) ? current.filter((item) => item !== value) : [...current, value])
}
</script>

<template>
  <div class="node-config-fields">
    <label
      v-for="key in schemaKeys"
      :key="key"
      class="field"
      :class="{
        'field-check': getFieldType(key) === 'boolean',
        'field-drop-target': dropTargetKey === key,
        'field-busy': uploadingKey === key,
      }"
    >
      <span class="field-label">{{ getFieldLabel(key) }}</span>

      <select
        v-if="isModeField(key)"
        class="field-input"
        :value="selectedMode"
        @change="setField('mode', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="mode in modeOptions" :key="mode" :value="mode">{{ mode }}</option>
      </select>

      <select
        v-else-if="isProviderField(key)"
        class="field-input"
        :value="String(fields.provider_id ?? '')"
        :disabled="providerOptions.length === 0"
        @change="setField('provider_id', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="providerId in providerOptions" :key="providerId" :value="providerId">
          {{ providerId }}
        </option>
      </select>

      <select
        v-else-if="isWebSearchField(key)"
        class="field-input"
        :value="normalizeSwitch(fields.web_search, 'disabled')"
        @change="setField('web_search', normalizeSwitch(($event.target as HTMLSelectElement).value, 'disabled'))"
      >
        <option v-for="option in switchOptions" :key="`web-${option.value}`" :value="option.value">
          {{ option.label }}
        </option>
      </select>

      <select
        v-else-if="isThinkingField(key)"
        class="field-input"
        :value="normalizeSwitch(fields.thinking, 'enabled')"
        @change="setField('thinking', normalizeSwitch(($event.target as HTMLSelectElement).value, 'enabled'))"
      >
        <option v-for="option in switchOptions" :key="`thinking-${option.value}`" :value="option.value">
          {{ option.label }}
        </option>
      </select>

      <div v-else-if="isToolsField(key)" class="tools-picker">
        <button
          v-for="tool in toolOptions"
          :key="`tool-${tool}`"
          type="button"
          class="tool-chip"
          :class="{ active: toolSelection.includes(tool) }"
          @click="toggleTool(tool)"
        >
          {{ tool }}
        </button>
      </div>

      <select
        v-else-if="isSelectField(key)"
        class="field-input"
        :value="String(fields[key] ?? '')"
        @change="setField(key, ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="option in getFieldOptions(key)" :key="`option-${key}-${option.value}`" :value="option.value">
          {{ option.label }}
        </option>
      </select>

      <textarea
        v-else-if="getFieldType(key) === 'text' || getFieldType(key) === 'json'"
        class="field-input field-textarea"
        rows="3"
        :value="getFieldText(key)"
        @input="setField(key, ($event.target as HTMLTextAreaElement).value)"
        @dragover="enableAssetDrop ? emit('field-dragover', key, $event) : undefined"
        @dragleave="enableAssetDrop ? emit('field-dragleave', key, $event) : undefined"
        @drop="enableAssetDrop ? emit('field-drop', key, $event) : undefined"
      ></textarea>

      <input
        v-else-if="getFieldType(key) === 'boolean'"
        class="field-checkbox"
        type="checkbox"
        :checked="isCheckedValue(fields[key])"
        @change="setField(key, ($event.target as HTMLInputElement).checked)"
      />

      <input
        v-else-if="!isWorkingPathField(key)"
        class="field-input"
        :type="getInputType(key)"
        v-bind="getInputAttrs(key)"
        :value="String(fields[key] ?? '')"
        @input="setField(key, ($event.target as HTMLInputElement).value)"
        @dragover="enableAssetDrop ? emit('field-dragover', key, $event) : undefined"
        @dragleave="enableAssetDrop ? emit('field-dragleave', key, $event) : undefined"
        @drop="enableAssetDrop ? emit('field-drop', key, $event) : undefined"
      />

      <WorkingPathField
        v-else
        :value="String(fields[key] ?? '')"
        :input-attrs="getInputAttrs(key)"
        @update-value="setField(key, $event)"
        @error="emit('field-error', $event)"
      />

      <span v-if="getFieldHint(key)" class="field-hint">{{ getFieldHint(key) }}</span>
      <span v-if="enableAssetDrop && isAssetFieldKey(key)" class="field-drop-hint">Drop files here to upload and fill this asset field.</span>
    </label>
  </div>
</template>

<style scoped>
.node-config-fields,
.field {
  display: flex;
  flex-direction: column;
}

.node-config-fields {
  gap: 12px;
}

.field {
  gap: 6px;
}

.field-check {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.field-label {
  font-size: 12px;
  font-weight: 600;
  color: #cbd5e1;
}

.field-input {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.88);
  color: #f8fafc;
  padding: 10px 12px;
  outline: none;
}

.field-input:focus {
  border-color: rgba(56, 189, 248, 0.7);
}

.field-textarea {
  min-height: 78px;
  resize: vertical;
  line-height: 1.4;
}

.field-checkbox {
  width: 16px;
  height: 16px;
}

.field-hint,
.field-drop-hint {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.78);
  line-height: 1.35;
}

.field-drop-target .field-input {
  border-color: rgba(45, 212, 191, 0.8);
  box-shadow: 0 0 0 1px rgba(45, 212, 191, 0.28);
}

.field-busy .field-input {
  opacity: 0.7;
}

.tools-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tool-chip {
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.7);
  color: rgba(226, 232, 240, 0.95);
  font-size: 11px;
  padding: 4px 10px;
}

.tool-chip.active {
  border-color: rgba(56, 189, 248, 0.7);
  background: rgba(14, 116, 144, 0.3);
}
</style>
