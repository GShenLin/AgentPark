<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getPrompt, listPrompts, savePrompt, type PromptLibraryKind, type ProviderInfo } from '../../api'
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
  reasoningEffortOptions,
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
  normalizeSchemaFieldValue,
} from '../../composables/nodeSchemaFields'
import FieldMultiSelect from './FieldMultiSelect.vue'
import WorkingPathField from './WorkingPathField.vue'

type NodeFields = Record<string, any>

const props = withDefaults(defineProps<{
  typeId: string
  schema: Record<string, any>
  fields: NodeFields
  providers: ProviderInfo[]
  availableTools: string[]
  enablePromptLibrary?: boolean
  dropTargetKey?: string
  uploadingKey?: string
  enableAssetDrop?: boolean
  resetKey?: string
}>(), {
  enablePromptLibrary: false,
  dropTargetKey: '',
  uploadingKey: '',
  enableAssetDrop: false,
  resetKey: '',
})

const emit = defineEmits<{
  'update-field': [key: string, value: any]
  'field-dragover': [key: string, event: DragEvent]
  'field-dragleave': [key: string, event: DragEvent]
  'field-drop': [key: string, event: DragEvent]
  'field-error': [message: string]
}>()

const defaultModeOrder = ['chat', 'image_generation', 'video_generation', 'imagechat', 'vision_understand']
const multiSelectSearchQueries = ref<Record<string, string>>({})
const promptActionBusy = ref('')
const promptActionMessage = ref('')
const promptLibraryMode = ref<'' | 'save' | 'load'>('')
const promptLibraryField = ref('')
const promptLibraryFiles = ref<string[]>([])
const promptSaveFilename = ref('system_prompt.txt')
const schemaKeys = computed(() => Object.keys(props.schema || {}).filter((key) => shouldShowField(key)))
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

function setField(key: string, value: any) {
  if (isPromptLibraryField(key)) promptActionMessage.value = ''
  emit('update-field', key, value)
}

function isPromptLibraryField(key: string) {
  const field = String(key || '').trim()
  return props.enablePromptLibrary && (field === 'system_prompt' || field === 'instruction')
}

function isPromptLibraryOpen(key: string) {
  return Boolean(isPromptLibraryField(key) && promptLibraryMode.value && promptLibraryField.value === String(key || '').trim())
}

function defaultPromptFilename(key: string) {
  return String(key || '').trim() === 'instruction' ? 'instruction.txt' : 'system_prompt.txt'
}

function promptLibraryKindForField(key: string): PromptLibraryKind {
  return String(key || '').trim() === 'instruction' ? 'instruction' : 'system_prompt'
}

function ensurePromptLibraryField(key: string) {
  const field = String(key || '').trim()
  if (promptLibraryField.value !== field) {
    promptLibraryField.value = field
    promptSaveFilename.value = defaultPromptFilename(field)
  }
}

function normalizePromptFilename(value: string) {
  const filename = String(value || '').trim()
  if (!filename) return ''
  return filename.toLowerCase().endsWith('.txt') ? filename : `${filename}.txt`
}

async function refreshPromptLibraryFiles(key: string) {
  promptLibraryFiles.value = (await listPrompts(promptLibraryKindForField(key)))
    .map((item) => String(item || '').trim())
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b))
}

function promptLibrarySelectValue() {
  const filename = normalizePromptFilename(promptSaveFilename.value)
  return promptLibraryFiles.value.includes(filename) ? filename : ''
}

function selectPromptLibraryFile(value: string) {
  const filename = normalizePromptFilename(value)
  if (filename) promptSaveFilename.value = filename
}

function promptActionError(error: unknown) {
  promptActionMessage.value = ''
  emit('field-error', String((error as { message?: unknown })?.message || error || '').trim())
}

async function saveSystemPrompt(key: string) {
  if (!isPromptLibraryField(key) || promptActionBusy.value) return
  const content = String(props.fields[key] ?? '')
  if (!content.trim()) {
    promptActionError(`${key} is empty; nothing to save.`)
    return
  }
  const filename = normalizePromptFilename(promptSaveFilename.value)
  if (!filename) {
    promptActionError('Prompt filename is required.')
    return
  }
  promptActionBusy.value = 'save'
  emit('field-error', '')
  try {
    await savePrompt(promptLibraryKindForField(key), filename, content)
    promptSaveFilename.value = filename
    await refreshPromptLibraryFiles(key)
    promptLibraryMode.value = ''
    promptActionMessage.value = `Saved ${filename}`
  } catch (error) {
    promptActionError(error)
  } finally {
    promptActionBusy.value = ''
  }
}

async function loadSystemPrompt(key: string) {
  await loadPromptFile(key, promptSaveFilename.value)
}

async function openPromptLibraryForField(mode: 'save' | 'load', key: string) {
  if (promptActionBusy.value) return
  const sameOpen = promptLibraryMode.value === mode && promptLibraryField.value === String(key || '').trim()
  if (sameOpen) {
    promptLibraryMode.value = ''
    return
  }
  ensurePromptLibraryField(key)
  promptLibraryMode.value = mode
  promptActionBusy.value = 'load'
  emit('field-error', '')
  try {
    await refreshPromptLibraryFiles(key)
    if (mode === 'load' && promptLibraryFiles.value.length) {
      promptSaveFilename.value = promptLibraryFiles.value[0] || ''
    }
  } catch (error) {
    promptActionError(error)
  } finally {
    promptActionBusy.value = ''
  }
}

async function loadPromptFile(key: string, requested: string) {
  if (!isPromptLibraryField(key) || promptActionBusy.value) return
  const filename = normalizePromptFilename(requested)
  if (!filename) {
    promptActionError('Prompt filename is required.')
    return
  }
  promptActionBusy.value = 'load'
  emit('field-error', '')
  try {
    const content = await getPrompt(promptLibraryKindForField(key), filename)
    promptSaveFilename.value = filename
    setField(key, content)
    promptLibraryMode.value = ''
    promptActionMessage.value = `Loaded ${filename}`
  } catch (error) {
    promptActionError(error)
  } finally {
    promptActionBusy.value = ''
  }
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

function isWebSearchField(key: string) {
  return (props.typeId === 'agent_node' || props.typeId === VIDEO_GENERATION_NODE_TYPE) && key === 'web_search'
}

function isThinkingField(key: string) {
  return props.typeId === 'agent_node' && key === 'thinking'
}

function isReasoningEffortField(key: string) {
  return props.typeId === 'agent_node' && key === 'reasoning_effort'
}

function shouldShowField(_key: string) {
  return true
}

function getSelectedProvider() {
  const providerId = String(props.fields.provider_id ?? '').trim()
  if (!providerId) return null
  return props.providers.find((provider) => String(provider.id || '').trim() === providerId) || null
}

function getProviderFeatureHint(key: string) {
  if (props.typeId !== 'agent_node') return ''
  if (!['web_search', 'thinking', 'reasoning_effort', 'tools'].includes(key)) return ''
  const provider = getSelectedProvider()
  const feature = provider?.features?.[key]
  if (!feature || typeof feature !== 'object') return ''
  const providerId = String(provider?.id || '').trim()
  const label = providerId ? `${providerId}: ` : ''
  const values = Array.isArray(feature.values) ? feature.values.map((item) => String(item || '').trim()).filter(Boolean) : []
  const requires = String(feature.requires || '').trim()
  if (feature.supported) {
    return `${label}${key} supported${values.length ? ` (${values.join(', ')})` : ''}.`
  }
  return `${label}${key} unsupported${requires ? `; requires ${requires}` : ''}.`
}

function isToolsField(key: string) {
  return props.typeId === 'agent_node' && key === 'tools'
}

function isToolSelectionField(key: string) {
  return isToolsField(key)
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
  const schemaHint = getSchemaFieldHint(props.schema, key)
  const providerHint = getProviderFeatureHint(key)
  return [schemaHint, providerHint].filter(Boolean).join(' ')
}

function isSelectField(key: string) {
  return isSchemaSelectField(props.schema, key)
}

function getFieldOptions(key: string) {
  if (isToolSelectionField(key)) {
    const schemaOptions = getSchemaFieldOptions(props.schema, key)
    if (schemaOptions.length) return schemaOptions
    return toolOptions.value.map((value) => ({ value, label: value }))
  }
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

function getMultiSelectValue(key: string) {
  if (isToolSelectionField(key)) {
    const allowedTools = getFieldOptions(key).map((option) => option.value)
    return normalizeToolSelection(props.fields[key], allowedTools)
  }
  return normalizeSchemaFieldValue(props.schema, key, props.fields[key]) as string[]
}

function getMultiSelectPlaceholder(key: string) {
  if (String(key || '').trim() === 'plugins') return 'Select plugins'
  if (isToolsField(key)) return 'Select tools'
  if (String(key || '').trim() === 'mcp_servers') return 'Select MCP servers'
  if (String(key || '').trim() === 'skills') return 'Select skills'
  return `Select ${getFieldLabel(key)}`
}

function getMultiSelectLabel(key: string) {
  const selected = new Set(getMultiSelectValue(key))
  const labels = getFieldOptions(key)
    .filter((option) => selected.has(option.value))
    .map((option) => option.label)
  if (!labels.length) return getMultiSelectPlaceholder(key)
  if (labels.length <= 2) return labels.join(', ')
  return `${labels.length} selected`
}

function getMultiSelectEmptyText(key: string) {
  if (String(key || '').trim() === 'plugins') return 'No plugins found.'
  if (isToolSelectionField(key)) return 'No tools found.'
  if (String(key || '').trim() === 'mcp_servers') return 'No MCP servers found.'
  if (String(key || '').trim() === 'skills') return 'No skills found.'
  return 'No options found.'
}

function getMultiSelectSearchQuery(key: string) {
  return String(multiSelectSearchQueries.value[key] || '')
}

function setMultiSelectSearchQuery(key: string, value: string) {
  multiSelectSearchQueries.value = {
    ...multiSelectSearchQueries.value,
    [key]: String(value || ''),
  }
}

function getMultiSelectSearchPlaceholder(key: string) {
  return `Search ${getFieldLabel(key)}`
}

function toggleMultiSelectOption(key: string, value: string) {
  const optionValue = String(value || '').trim()
  if (!optionValue) return
  const current = getMultiSelectValue(key)
  const next = current.includes(optionValue)
    ? current.filter((item) => item !== optionValue)
    : [...current, optionValue]
  setField(key, next)
}

function isDropdownMultiSelectField(key: string) {
  if (isToolsField(key)) return true
  return String(props.schema?.[key]?.type || '').trim().toLowerCase() === 'multiselect'
}

function getReasoningEffortValue() {
  return props.fields.reasoning_effort ?? 'high'
}

watch(
  () => props.resetKey,
  () => {
    multiSelectSearchQueries.value = {}
  },
)

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
      <span class="field-head" :class="{ 'field-head-search': isDropdownMultiSelectField(key) }">
        <span class="field-label">{{ getFieldLabel(key) }}</span>
        <span v-if="isPromptLibraryField(key)" class="field-prompt-actions">
          <button
            class="field-prompt-btn field-prompt-save"
            type="button"
            :disabled="!!promptActionBusy"
            @click.prevent.stop="openPromptLibraryForField('save', key)"
          >
            Save
          </button>
          <button
            class="field-prompt-btn field-prompt-load"
            type="button"
            :disabled="!!promptActionBusy"
            @click.prevent.stop="openPromptLibraryForField('load', key)"
          >
            {{ promptActionBusy === 'load' ? 'Loading...' : 'Load' }}
          </button>
        </span>
        <input
          v-if="isDropdownMultiSelectField(key)"
          class="field-search-input"
          type="search"
          :placeholder="getMultiSelectSearchPlaceholder(key)"
          :value="getMultiSelectSearchQuery(key)"
          @click.stop
          @keydown.stop
          @input="setMultiSelectSearchQuery(key, ($event.target as HTMLInputElement).value)"
        />
      </span>

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
        :value="normalizeSwitch(fields.thinking, 'disabled')"
        @change="setField('thinking', normalizeSwitch(($event.target as HTMLSelectElement).value, 'disabled'))"
      >
        <option v-for="option in switchOptions" :key="`thinking-${option.value}`" :value="option.value">
          {{ option.label }}
        </option>
      </select>

      <select
        v-else-if="isReasoningEffortField(key)"
        class="field-input"
        :value="getReasoningEffortValue()"
        @change="setField('reasoning_effort', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="option in reasoningEffortOptions" :key="`reasoning-${option.value}`" :value="option.value">
          {{ option.label }}
        </option>
      </select>

      <FieldMultiSelect
        v-else-if="isDropdownMultiSelectField(key)"
        :label="getMultiSelectLabel(key)"
        :options="getFieldOptions(key)"
        :selected-values="getMultiSelectValue(key)"
        :empty-text="getMultiSelectEmptyText(key)"
        :search-query="getMultiSelectSearchQuery(key)"
        :reset-key="`${resetKey}:${key}`"
        @toggle="toggleMultiSelectOption(key, $event)"
      />

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

      <div v-if="isPromptLibraryOpen(key)" class="field-prompt-library" @click.stop @keydown.stop>
        <template v-if="promptLibraryMode === 'save'">
          <select
            v-if="promptLibraryFiles.length"
            class="field-input field-prompt-name field-prompt-select"
            :value="promptLibrarySelectValue()"
            @change="selectPromptLibraryFile(($event.target as HTMLSelectElement).value)"
          >
            <option value="" disabled>Select saved prompt</option>
            <option v-for="filename in promptLibraryFiles" :key="filename" :value="filename">{{ filename }}</option>
          </select>
          <input
            v-model="promptSaveFilename"
            class="field-input field-prompt-name field-prompt-custom-name"
            type="text"
            :placeholder="defaultPromptFilename(key)"
          />
          <button
            class="field-prompt-btn field-prompt-confirm field-prompt-save"
            type="button"
            :disabled="!!promptActionBusy"
            @click.prevent.stop="saveSystemPrompt(key)"
          >
            {{ promptActionBusy === 'save' ? 'Saving...' : 'Save' }}
          </button>
        </template>
        <template v-else>
          <select
            v-if="promptLibraryFiles.length"
            class="field-input field-prompt-name"
            :value="promptLibrarySelectValue()"
            @change="selectPromptLibraryFile(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="filename in promptLibraryFiles" :key="filename" :value="filename">{{ filename }}</option>
          </select>
          <span v-else class="field-prompt-empty">No saved prompts found.</span>
          <button
            class="field-prompt-btn field-prompt-confirm field-prompt-load"
            type="button"
            :disabled="!!promptActionBusy || !promptLibraryFiles.length"
            @click.prevent.stop="loadSystemPrompt(key)"
          >
            {{ promptActionBusy === 'load' ? 'Loading...' : 'Load' }}
          </button>
        </template>
      </div>

      <span v-if="getFieldHint(key)" class="field-hint">{{ getFieldHint(key) }}</span>
      <span v-if="isPromptLibraryField(key) && promptLibraryField === key && promptActionMessage" class="field-prompt-message">{{ promptActionMessage }}</span>
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
  color: var(--theme-panel-node-side-editor-text-secondary, #cbd5e1);
}

.field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.field-head-search .field-label {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-search-input {
  flex: 0 1 150px;
  min-width: 96px;
  max-width: 56%;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.22));
  border-radius: 8px;
  background: var(--theme-panel-node-side-editor-input-background, rgba(15, 23, 42, 0.88));
  color: var(--theme-panel-node-side-editor-input-text, #f8fafc);
  padding: 6px 8px;
  font-size: 11px;
  line-height: 1.2;
  outline: none;
}

.field-search-input:focus {
  border-color: rgba(56, 189, 248, 0.7);
}

.field-search-input::placeholder {
  color: rgba(148, 163, 184, 0.74);
}

.field-prompt-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.field-prompt-btn {
  border: 1px solid var(--theme-panel-node-side-editor-button-border, rgba(148, 163, 184, 0.28));
  border-radius: 8px;
  background: var(--theme-panel-node-side-editor-button-background, rgba(15, 23, 42, 0.92));
  color: var(--theme-panel-node-side-editor-button-text, #f8fafc);
  cursor: pointer;
  font-size: 11px;
  line-height: 1.2;
  min-width: 42px;
  padding: 5px 8px;
}

.field-prompt-save {
  border-color: rgba(34, 197, 94, 0.46);
  background: rgba(22, 101, 52, 0.36);
  color: #bbf7d0;
}

.field-prompt-load {
  border-color: rgba(59, 130, 246, 0.48);
  background: rgba(30, 64, 175, 0.34);
  color: #bfdbfe;
}

.field-prompt-save:hover:not(:disabled) {
  border-color: rgba(74, 222, 128, 0.68);
  background: rgba(22, 163, 74, 0.42);
}

.field-prompt-load:hover:not(:disabled) {
  border-color: rgba(96, 165, 250, 0.72);
  background: rgba(37, 99, 235, 0.42);
}

.field-prompt-btn:disabled {
  cursor: default;
  opacity: 0.58;
}

.field-prompt-library {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.field-prompt-name {
  flex: 1 1 auto;
  min-width: 0;
  padding: 8px 10px;
  font-size: 12px;
}

.field-prompt-select,
.field-prompt-custom-name {
  flex-basis: 160px;
}

.field-prompt-confirm {
  flex: 0 0 auto;
  min-width: 54px;
  padding: 8px 10px;
}

.field-prompt-empty {
  flex: 1 1 auto;
  min-width: 0;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  color: rgba(148, 163, 184, 0.78);
  font-size: 12px;
  line-height: 1.2;
  padding: 9px 10px;
}

.field-input {
  width: 100%;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.22));
  border-radius: 10px;
  background: var(--theme-panel-node-side-editor-input-background, rgba(15, 23, 42, 0.88));
  color: var(--theme-panel-node-side-editor-input-text, #f8fafc);
  padding: 10px 12px;
  outline: none;
}

.field-input:focus {
  border-color: var(--theme-panel-node-side-editor-input-focus-border, rgba(56, 189, 248, 0.7));
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
.field-drop-hint,
.field-prompt-message {
  font-size: 11px;
  color: var(--theme-panel-node-side-editor-text-secondary, rgba(148, 163, 184, 0.78));
  line-height: 1.35;
}

.field-prompt-message {
  color: #99f6e4;
}

.field-drop-target .field-input {
  border-color: rgba(45, 212, 191, 0.8);
  box-shadow: 0 0 0 1px rgba(45, 212, 191, 0.28);
}

.field-busy .field-input {
  opacity: 0.7;
}

</style>
