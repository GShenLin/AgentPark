<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getPrompt, listPrompts, savePrompt, type PromptLibraryKind, type ProviderInfo } from '../../api'
import { ASSET_FIELD_KEYS } from '../../composables/droppedPaths'
import {
  agentProviderModes,
  cliProviderModes,
  CLAUDE_NODE_TYPE,
  dedupeStrings,
  GUI_AGENT_NODE_TYPE,
  normalizeSwitch,
  normalizeToolSelection,
  providerReasoningEffortOptions,
  providerModes,
  switchOptions,
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
import FieldCombobox from './FieldCombobox.vue'
import FieldColorPicker from './FieldColorPicker.vue'
import FieldFileListPicker from './FieldFileListPicker.vue'
import FieldImageDimensions from './FieldImageDimensions.vue'
import {
  createNodeConfigFieldSections,
  type NodeConfigFieldSection,
} from './nodeConfigFieldGroups'
import ActionButton from '../ActionButton.vue'
import ExpandableTextarea from '../ExpandableTextarea.vue'
import FormCheckbox from '../FormCheckbox.vue'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'
import ProviderSelect from '../ProviderSelect.vue'
import WorkingPathField from './WorkingPathField.vue'
import { t } from '../../i18n'

type NodeFields = Record<string, any>
type NodeConfigFieldApplyMode = 'immediate' | 'explicit'

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
  explicitDirtyKeys?: string[]
  applyingKey?: string
  applyDisabled?: boolean
}>(), {
  enablePromptLibrary: false,
  dropTargetKey: '',
  uploadingKey: '',
  enableAssetDrop: false,
  resetKey: '',
  explicitDirtyKeys: () => [],
  applyingKey: '',
  applyDisabled: false,
})

const emit = defineEmits<{
  'update-field': [key: string, value: any, applyMode?: NodeConfigFieldApplyMode]
  'field-dragover': [key: string, event: DragEvent]
  'field-dragleave': [key: string, event: DragEvent]
  'field-drop': [key: string, event: DragEvent]
  'field-error': [message: string]
  'apply-field': [key: string]
}>()

const multiSelectSearchQueries = ref<Record<string, string>>({})
const promptActionBusy = ref('')
const promptActionMessage = ref('')
const promptLibraryMode = ref<'' | 'save' | 'load'>('')
const promptLibraryField = ref('')
const promptLibraryFiles = ref<string[]>([])
const promptSaveFilename = ref('system_prompt.txt')
const schemaKeys = computed(() => Object.keys(props.schema || {}).filter((key) => (
  shouldShowField(key)
)))
const providerOptions = computed(() => dedupeStrings(
  props.providers
    .filter((provider) => {
      if (props.typeId === 'agent_node') return agentProviderModes(provider).length > 0
      if (['codex_node', CLAUDE_NODE_TYPE].includes(props.typeId)) return cliProviderModes(provider).length > 0
      return true
    })
    .map((provider) => String(provider.id || '').trim())
    .filter(Boolean),
).sort((left, right) => left.localeCompare(right)))
const toolOptions = computed(() => dedupeStrings(props.availableTools).sort((a, b) => a.localeCompare(b)))
const activeSupportModes = computed(() => {
  const provider = getSelectedProvider()
  if (!provider) return []
  return props.typeId === 'agent_node' ? agentProviderModes(provider) : providerModes(provider)
})
const fieldSections = computed(() => createNodeConfigFieldSections(
  props.typeId,
  schemaKeys.value,
  props.schema,
  activeSupportModes.value,
))
const fieldGroupOpen = ref<Record<string, boolean>>({})
const explicitDirtyKeySet = computed(() => new Set(props.explicitDirtyKeys))

function setField(key: string, value: any, applyMode: NodeConfigFieldApplyMode = 'immediate') {
  if (isPromptLibraryField(key)) promptActionMessage.value = ''
  emit('update-field', key, value, applyMode)
}

function setExplicitField(key: string, value: any) {
  setField(key, value, 'explicit')
}

function isExplicitDirty(key: string) {
  return explicitDirtyKeySet.value.has(key)
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
    setExplicitField(key, content)
    promptLibraryMode.value = ''
    promptActionMessage.value = `Loaded ${filename}`
  } catch (error) {
    promptActionError(error)
  } finally {
    promptActionBusy.value = ''
  }
}

function isProviderField(key: string) {
  if (key !== 'provider_id') return false
  return (
    props.typeId === 'agent_node' ||
    props.typeId === 'codex_node' ||
    props.typeId === CLAUDE_NODE_TYPE ||
    props.typeId === GUI_AGENT_NODE_TYPE
  )
}

function setProvider(providerId: string) {
  setField('provider_id', String(providerId || '').trim())
}

function isWebSearchField(key: string) {
  return props.typeId === 'agent_node' && key === 'web_search'
}

function isThinkingField(key: string) {
  return props.typeId === 'agent_node' && key === 'thinking'
}

function isReasoningEffortField(key: string) {
  return props.typeId === 'agent_node' && key === 'reasoning_effort'
}

function shouldShowField(key: string) {
  const field = props.schema?.[String(key || '').trim()]
  if (!(field && typeof field === 'object' && !Array.isArray(field))) return true
  if (field.hidden === true) return false
  const operations = Array.isArray(field.operations) ? field.operations.map((item: unknown) => String(item || '').trim()) : []
  if (operations.length > 0) {
    return operations.includes(String(props.fields.audio_operation || 'generate').trim())
  }
  const visibleWhen = field.visible_when
  if (visibleWhen && typeof visibleWhen === 'object' && !Array.isArray(visibleWhen)) {
    const dependency = String(visibleWhen.field || '').trim()
    if (!dependency || !Object.prototype.hasOwnProperty.call(visibleWhen, 'equals')) return false
    return props.fields[dependency] === visibleWhen.equals
  }
  return true
}

function isComboboxField(key: string) {
  return String(props.schema?.[key]?.type || '').trim().toLowerCase() === 'combobox'
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

function getFieldContainerTag(key: string) {
  return ['color', 'image_dimensions'].includes(getFieldType(key)) ? 'div' : 'label'
}

function getInputType(key: string): 'text' | 'number' {
  return getSchemaInputType(props.schema, key) === 'number' ? 'number' : 'text'
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

function getReasoningEffortOptions() {
  return providerReasoningEffortOptions(getSelectedProvider())
}

function resetFieldGroups() {
  fieldGroupOpen.value = {}
}

function isFieldGroupOpen(section: NodeConfigFieldSection) {
  if (!section.collapsible) return true
  return fieldGroupOpen.value[section.id] ?? section.defaultOpen
}

function onFieldGroupToggle(section: NodeConfigFieldSection, event: Event) {
  if (!section.collapsible) return
  const target = event.currentTarget
  if (!(target instanceof HTMLDetailsElement)) return
  fieldGroupOpen.value = {
    ...fieldGroupOpen.value,
    [section.id]: target.open,
  }
}

watch(
  () => [props.resetKey, props.typeId, activeSupportModes.value.join('|')],
  () => {
    multiSelectSearchQueries.value = {}
    resetFieldGroups()
  },
)

</script>

<template>
  <div class="node-config-fields">
    <component
      :is="section.collapsible ? 'details' : 'div'"
      v-for="section in fieldSections"
      :key="section.id"
      :class="section.collapsible ? 'config-field-group' : 'config-field-ungrouped'"
      :open="section.collapsible ? isFieldGroupOpen(section) : undefined"
      @toggle="onFieldGroupToggle(section, $event)"
    >
      <summary v-if="section.collapsible" class="config-field-group-summary">
        <span>{{ section.label }}</span>
        <span class="config-field-group-chevron" aria-hidden="true">›</span>
      </summary>

      <div class="config-field-group-fields">
        <component
          :is="getFieldContainerTag(key)"
          v-for="key in section.keys"
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
            <span v-if="isExplicitDirty(key) || isPromptLibraryField(key)" class="field-prompt-actions">
              <ActionButton
                v-if="isExplicitDirty(key)"
                variant="primary"
                compact
                :disabled="applyDisabled || !!applyingKey || !!promptActionBusy"
                @click.prevent.stop="emit('apply-field', key)"
              >
                {{ applyingKey === key ? 'Applying...' : 'Apply' }}
              </ActionButton>
              <ActionButton
                v-if="isPromptLibraryField(key)"
                compact
                :disabled="!!promptActionBusy"
                @click.prevent.stop="openPromptLibraryForField('save', key)"
              >
                Save
              </ActionButton>
              <ActionButton
                v-if="isPromptLibraryField(key)"
                compact
                :disabled="!!promptActionBusy"
                @click.prevent.stop="openPromptLibraryForField('load', key)"
              >
                {{ promptActionBusy === 'load' ? 'Loading...' : 'Load' }}
              </ActionButton>
            </span>
            <FormTextInput
              v-if="isDropdownMultiSelectField(key)"
              class="field-search-input"
              type="search"
              compact
              :placeholder="getMultiSelectSearchPlaceholder(key)"
              :model-value="getMultiSelectSearchQuery(key)"
              @click.stop
              @keydown.stop
              @update:model-value="setMultiSelectSearchQuery(key, $event)"
            />
          </span>

      <FieldCombobox
        v-if="isComboboxField(key)"
        :id="`node-config-${typeId}-${key}`"
        :value="String(fields[key] ?? '')"
        :options="getFieldOptions(key)"
        :reset-key="`${resetKey}:${key}`"
        @update-value="setField(key, $event)"
      />

      <ProviderSelect
        v-else-if="isProviderField(key)"
        class="field-input"
        :model-value="String(fields.provider_id ?? '')"
        :providers="providers"
        :option-ids="providerOptions"
        :disabled="providerOptions.length === 0"
        @change="setProvider($event)"
      />

      <FormSelect
        v-else-if="isWebSearchField(key)"
        class="field-input"
        :model-value="normalizeSwitch(fields.web_search, 'disabled')"
        @change="setField('web_search', normalizeSwitch($event, 'disabled'))"
      >
        <option v-for="option in switchOptions" :key="`web-${option.value}`" :value="option.value">
          {{ option.label }}
        </option>
      </FormSelect>

      <FormSelect
        v-else-if="isThinkingField(key)"
        class="field-input"
        :model-value="normalizeSwitch(fields.thinking, 'disabled')"
        @change="setField('thinking', normalizeSwitch($event, 'disabled'))"
      >
        <option v-for="option in switchOptions" :key="`thinking-${option.value}`" :value="option.value">
          {{ option.label }}
        </option>
      </FormSelect>

      <FormSelect
        v-else-if="isReasoningEffortField(key)"
        class="field-input"
        :model-value="getReasoningEffortValue()"
        @change="setField('reasoning_effort', $event)"
      >
        <option v-for="option in getReasoningEffortOptions()" :key="`reasoning-${option.value}`" :value="option.value">
          {{ option.label }}
        </option>
      </FormSelect>

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

      <FieldImageDimensions
        v-else-if="getFieldType(key) === 'image_dimensions'"
        :value="fields[key]"
        :aspect-ratio-value="fields.image_aspect_ratio"
        :field-schema="schema[key]"
        :reset-key="`${resetKey}:${key}`"
        @update-value="setField(key, $event)"
        @update-aspect-ratio="setField('image_aspect_ratio', $event)"
      />

      <FormSelect
        v-else-if="isSelectField(key)"
        class="field-input"
        :model-value="String(fields[key] ?? '')"
        @change="setField(key, $event)"
      >
        <option v-for="option in getFieldOptions(key)" :key="`option-${key}-${option.value}`" :value="option.value">
          {{ option.label }}
        </option>
      </FormSelect>

      <WorkingPathField
        v-else-if="isWorkingPathField(key)"
        :value="String(fields[key] ?? '')"
        :input-attrs="getInputAttrs(key)"
        :remote-enabled="isCheckedValue(fields.remote_enabled)"
        :remote-worker-id="String(fields.remote_worker_id ?? '')"
        @update-value="setField(key, $event)"
        @update-remote="setField('remote_enabled', $event)"
        @update-worker="setField('remote_worker_id', $event)"
        @error="emit('field-error', $event)"
      />

      <FieldColorPicker
        v-else-if="getFieldType(key) === 'color'"
        :value="String(fields[key] ?? '')"
        :default-color="String(schema[key]?.default_color || '#FFFFFF')"
        :auto-label="String(schema[key]?.auto_label || 'Auto')"
        @update-value="setField(key, $event)"
      />

      <FieldFileListPicker
        v-else-if="getFieldType(key) === 'file_list'"
        :value="fields[key]"
        :root-path="String(fields.working_path ?? '')"
        :label="getFieldLabel(key)"
        :reset-key="`${resetKey}:${key}`"
        @update-value="setField(key, $event)"
      />

      <ExpandableTextarea
        v-else-if="getFieldType(key) === 'text' || getFieldType(key) === 'json'"
        :model-value="getFieldText(key)"
        :title="getFieldLabel(key)"
        :aria-label="getFieldLabel(key)"
        :rows="3"
        @update:model-value="setExplicitField(key, $event)"
        @dragover="enableAssetDrop ? emit('field-dragover', key, $event) : undefined"
        @dragleave="enableAssetDrop ? emit('field-dragleave', key, $event) : undefined"
        @drop="enableAssetDrop ? emit('field-drop', key, $event) : undefined"
      />

      <FormCheckbox
        v-else-if="getFieldType(key) === 'boolean'"
        class="field-checkbox"
        :model-value="isCheckedValue(fields[key])"
        @update:model-value="setField(key, $event)"
      />

      <FormTextInput
        v-else
        class="field-input"
        :type="getInputType(key)"
        v-bind="getInputAttrs(key)"
        :model-value="String(fields[key] ?? '')"
        @update:model-value="setField(key, $event)"
        @dragover="enableAssetDrop ? emit('field-dragover', key, $event) : undefined"
        @dragleave="enableAssetDrop ? emit('field-dragleave', key, $event) : undefined"
        @drop="enableAssetDrop ? emit('field-drop', key, $event) : undefined"
      />

      <div v-if="isPromptLibraryOpen(key)" class="field-prompt-library" @click.stop @keydown.stop>
        <template v-if="promptLibraryMode === 'save'">
          <FormSelect
            v-if="promptLibraryFiles.length"
            class="field-input field-prompt-name field-prompt-select"
            :model-value="promptLibrarySelectValue()"
            @change="selectPromptLibraryFile"
          >
            <option value="" disabled>{{ t('board.selectPrompt') }}</option>
            <option v-for="filename in promptLibraryFiles" :key="filename" :value="filename">{{ filename }}</option>
          </FormSelect>
          <FormTextInput
            v-model="promptSaveFilename"
            class="field-input field-prompt-name field-prompt-custom-name"
            :placeholder="defaultPromptFilename(key)"
          />
          <ActionButton
            class="field-prompt-confirm"
            variant="primary"
            compact
            :disabled="!!promptActionBusy"
            @click.prevent.stop="saveSystemPrompt(key)"
          >
            {{ promptActionBusy === 'save' ? 'Saving...' : 'Save' }}
          </ActionButton>
        </template>
        <template v-else>
          <FormSelect
            v-if="promptLibraryFiles.length"
            class="field-input field-prompt-name"
            :model-value="promptLibrarySelectValue()"
            @change="selectPromptLibraryFile"
          >
            <option v-for="filename in promptLibraryFiles" :key="filename" :value="filename">{{ filename }}</option>
          </FormSelect>
          <span v-else class="field-prompt-empty">{{ t('board.noPrompts') }}</span>
          <ActionButton
            class="field-prompt-confirm"
            variant="primary"
            compact
            :disabled="!!promptActionBusy || !promptLibraryFiles.length"
            @click.prevent.stop="loadSystemPrompt(key)"
          >
            {{ promptActionBusy === 'load' ? 'Loading...' : 'Load' }}
          </ActionButton>
        </template>
      </div>

          <span v-if="getFieldHint(key)" class="field-hint">{{ getFieldHint(key) }}</span>
          <span v-if="isPromptLibraryField(key) && promptLibraryField === key && promptActionMessage" class="field-prompt-message">{{ promptActionMessage }}</span>
          <span v-if="enableAssetDrop && isAssetFieldKey(key)" class="field-drop-hint">{{ t('board.dropAssets') }}</span>
        </component>
      </div>
    </component>

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
  --form-control-border: var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.22));
  --form-control-background: var(--theme-panel-node-side-editor-input-background, rgba(15, 23, 42, 0.88));
  --form-control-text: var(--theme-panel-node-side-editor-input-text, #f8fafc);
  --form-control-focus: var(--theme-panel-node-side-editor-input-focus-border, rgba(56, 189, 248, 0.7));
}

.config-field-ungrouped,
.config-field-group-fields {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.config-field-group {
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.22));
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.28);
  overflow: hidden;
}

.config-field-group-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  color: var(--theme-panel-node-side-editor-text-secondary, #cbd5e1);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  list-style: none;
  user-select: none;
}

.config-field-group-summary::-webkit-details-marker {
  display: none;
}

.config-field-group-summary:hover {
  background: rgba(148, 163, 184, 0.08);
}

.config-field-group-chevron {
  color: rgba(148, 163, 184, 0.82);
  font-size: 18px;
  line-height: 1;
  transform: rotate(0deg);
  transition: transform 0.16s ease;
}

.config-field-group[open] .config-field-group-chevron {
  transform: rotate(90deg);
}

.config-field-group-fields {
  padding: 2px 12px 12px;
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
}

.field-prompt-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
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

.field-drop-target :deep(.expandable-textarea__input) {
  border-color: rgba(45, 212, 191, 0.8);
  box-shadow: 0 0 0 1px rgba(45, 212, 191, 0.28);
}

.field-busy .field-input {
  opacity: 0.7;
}

.field-busy :deep(.expandable-textarea__input) {
  opacity: 0.7;
}

</style>
