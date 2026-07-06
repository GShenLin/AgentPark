<script setup lang="ts">
import { computed, ref } from 'vue'
import { getPrompt, listPrompts, savePrompt, type ProviderInfo } from '../../api'
import CompanionCapabilitySelect, { type CompanionCapabilityOption } from './CompanionCapabilitySelect.vue'

const props = defineProps<{
  data: Record<string, unknown>
  providers: ProviderInfo[]
  availableTools: string[]
  capabilityOptions: Record<string, CompanionCapabilityOption[]>
}>()

const emit = defineEmits<{
  'update:data': [value: Record<string, unknown>]
}>()

const modeOptions = ['chat', 'imagechat', 'vision_understand']
const switchOptions = ['disabled', 'enabled']
const reasoningEffortOptions = ['', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'auto']
const promptActionBusy = ref('')
const promptActionMessage = ref('')
const promptLibraryMode = ref<'' | 'save' | 'load'>('')
const promptLibraryFiles = ref<string[]>([])
const promptSaveFilename = ref('system_prompt.txt')

const providerOptions = computed(() =>
  props.providers
    .filter((provider) => provider.supportmode.includes('chat') || provider.supportmode.includes('imagechat'))
    .map((provider) => String(provider.id || '').trim())
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b)),
)
const fallbackToolOptions = computed(() => props.availableTools.map((value) => ({ value, label: value })))

function cloneData() {
  return JSON.parse(JSON.stringify(props.data || {})) as Record<string, unknown>
}

function stringValue(key: string) {
  return String(props.data[key] ?? '')
}

function listValue(key: string) {
  const value = props.data[key]
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item || '').trim()).filter(Boolean)
}

function capabilityOptions(key: string) {
  const options = props.capabilityOptions[key] || []
  if (key === 'tools' && options.length === 0) return fallbackToolOptions.value
  return options
}

function setField(key: string, value: unknown) {
  if (key === 'system_prompt') promptActionMessage.value = ''
  const next = cloneData()
  if (value === '' || value === null || value === undefined) {
    delete next[key]
  } else {
    next[key] = value
  }
  emit('update:data', next)
}

function setListField(key: string, values: string[]) {
  setField(key, values.map((item) => String(item || '').trim()).filter(Boolean))
}

function normalizePromptFilename(value: string) {
  const filename = String(value || '').trim()
  if (!filename) return ''
  return filename.toLowerCase().endsWith('.txt') ? filename : `${filename}.txt`
}

async function refreshPromptLibraryFiles() {
  promptLibraryFiles.value = (await listPrompts('system_prompt'))
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
  promptActionMessage.value = String((error as { message?: unknown })?.message || error || '').trim()
}

async function openPromptLibrary(mode: 'save' | 'load') {
  if (promptActionBusy.value) return
  promptLibraryMode.value = promptLibraryMode.value === mode ? '' : mode
  promptActionBusy.value = 'load'
  promptActionMessage.value = ''
  try {
    await refreshPromptLibraryFiles()
    if (mode === 'load' && promptLibraryFiles.value.length) {
      promptSaveFilename.value = promptLibraryFiles.value[0] || ''
    }
  } catch (error) {
    promptActionError(error)
  } finally {
    promptActionBusy.value = ''
  }
}

async function saveSystemPrompt() {
  if (promptActionBusy.value) return
  const content = stringValue('system_prompt')
  if (!content.trim()) {
    promptActionError('system_prompt is empty; nothing to save.')
    return
  }
  const filename = normalizePromptFilename(promptSaveFilename.value)
  if (!filename) {
    promptActionError('Prompt filename is required.')
    return
  }
  promptActionBusy.value = 'save'
  promptActionMessage.value = ''
  try {
    await savePrompt('system_prompt', filename, content)
    promptSaveFilename.value = filename
    await refreshPromptLibraryFiles()
    promptLibraryMode.value = ''
    promptActionMessage.value = `Saved ${filename}`
  } catch (error) {
    promptActionError(error)
  } finally {
    promptActionBusy.value = ''
  }
}

async function loadSystemPrompt() {
  if (promptActionBusy.value) return
  const filename = normalizePromptFilename(promptSaveFilename.value)
  if (!filename) {
    promptActionError('Prompt filename is required.')
    return
  }
  promptActionBusy.value = 'load'
  promptActionMessage.value = ''
  try {
    const content = await getPrompt('system_prompt', filename)
    promptSaveFilename.value = filename
    setField('system_prompt', content)
    promptLibraryMode.value = ''
    promptActionMessage.value = `Loaded ${filename}`
  } catch (error) {
    promptActionError(error)
  } finally {
    promptActionBusy.value = ''
  }
}
</script>

<template>
  <div class="companion-form">
    <section class="settings-group">
      <h2>Model</h2>
      <div class="form-grid">
        <label>
          <span>Provider</span>
          <select :value="stringValue('provider_id')" @change="setField('provider_id', ($event.target as HTMLSelectElement).value)">
            <option value="">Unset</option>
            <option v-for="providerId in providerOptions" :key="providerId" :value="providerId">{{ providerId }}</option>
          </select>
        </label>
        <label>
          <span>Mode</span>
          <select :value="stringValue('mode') || 'chat'" @change="setField('mode', ($event.target as HTMLSelectElement).value)">
            <option v-for="mode in modeOptions" :key="mode" :value="mode">{{ mode }}</option>
          </select>
        </label>
        <label>
          <span>Web Search</span>
          <select :value="stringValue('web_search') || 'disabled'" @change="setField('web_search', ($event.target as HTMLSelectElement).value)">
            <option v-for="option in switchOptions" :key="option" :value="option">{{ option }}</option>
          </select>
        </label>
        <label>
          <span>Thinking</span>
          <select :value="stringValue('thinking') || 'disabled'" @change="setField('thinking', ($event.target as HTMLSelectElement).value)">
            <option v-for="option in switchOptions" :key="option" :value="option">{{ option }}</option>
          </select>
        </label>
        <label>
          <span>Reasoning Effort</span>
          <select :value="stringValue('reasoning_effort')" @change="setField('reasoning_effort', ($event.target as HTMLSelectElement).value)">
            <option v-for="option in reasoningEffortOptions" :key="option || 'unset'" :value="option">{{ option || 'Unset' }}</option>
          </select>
        </label>
        <label>
          <span>Working Path</span>
          <input :value="stringValue('working_path')" @input="setField('working_path', ($event.target as HTMLInputElement).value)" />
        </label>
      </div>
      <label class="wide-field">
        <span class="field-head">
          <span>System Prompt</span>
          <span class="field-prompt-actions">
            <button
              class="field-prompt-btn field-prompt-save"
              type="button"
              :disabled="!!promptActionBusy"
              @click.prevent.stop="openPromptLibrary('save')"
            >
              Save
            </button>
            <button
              class="field-prompt-btn field-prompt-load"
              type="button"
              :disabled="!!promptActionBusy"
              @click.prevent.stop="openPromptLibrary('load')"
            >
              {{ promptActionBusy === 'load' ? 'Loading...' : 'Load' }}
            </button>
          </span>
        </span>
        <textarea :value="stringValue('system_prompt')" rows="5" @input="setField('system_prompt', ($event.target as HTMLTextAreaElement).value)"></textarea>
        <div v-if="promptLibraryMode" class="field-prompt-library" @click.stop @keydown.stop>
          <template v-if="promptLibraryMode === 'save'">
            <select
              v-if="promptLibraryFiles.length"
              class="field-prompt-name field-prompt-select"
              :value="promptLibrarySelectValue()"
              @change="selectPromptLibraryFile(($event.target as HTMLSelectElement).value)"
            >
              <option value="" disabled>Select saved prompt</option>
              <option v-for="filename in promptLibraryFiles" :key="filename" :value="filename">{{ filename }}</option>
            </select>
            <input
              v-model="promptSaveFilename"
              class="field-prompt-name field-prompt-custom-name"
              type="text"
              placeholder="system_prompt.txt"
            />
            <button
              class="field-prompt-btn field-prompt-confirm field-prompt-save"
              type="button"
              :disabled="!!promptActionBusy"
              @click.prevent.stop="saveSystemPrompt"
            >
              {{ promptActionBusy === 'save' ? 'Saving...' : 'Save' }}
            </button>
          </template>
          <template v-else>
            <select
              v-if="promptLibraryFiles.length"
              class="field-prompt-name"
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
              @click.prevent.stop="loadSystemPrompt"
            >
              {{ promptActionBusy === 'load' ? 'Loading...' : 'Load' }}
            </button>
          </template>
        </div>
        <span v-if="promptActionMessage" class="field-prompt-message">{{ promptActionMessage }}</span>
      </label>
    </section>

    <section class="settings-group">
      <h2>Capabilities</h2>
      <div class="capability-grid">
        <CompanionCapabilitySelect
          title="Tools"
          :values="listValue('tools')"
          :options="capabilityOptions('tools')"
          empty-text="No tools found."
          add-placeholder="Tool id"
          @update:values="setListField('tools', $event)"
        />
        <CompanionCapabilitySelect
          title="MCP Servers"
          :values="listValue('mcp_servers')"
          :options="capabilityOptions('mcp_servers')"
          empty-text="No MCP servers found."
          add-placeholder="MCP server id"
          @update:values="setListField('mcp_servers', $event)"
        />
        <CompanionCapabilitySelect
          title="Skills"
          :values="listValue('skills')"
          :options="capabilityOptions('skills')"
          empty-text="No skills found."
          add-placeholder="Skill id"
          @update:values="setListField('skills', $event)"
        />
        <CompanionCapabilitySelect
          title="Plugins"
          :values="listValue('plugins')"
          :options="capabilityOptions('plugins')"
          empty-text="No plugins found."
          add-placeholder="Plugin id"
          @update:values="setListField('plugins', $event)"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.companion-form {
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

.settings-group h2 {
  margin: 0 0 10px;
  font-size: 15px;
}

.form-grid,
.capability-grid {
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

.wide-field {
  margin-top: 12px;
}

.field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.field-prompt-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.field-prompt-btn {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.92);
  color: #f8fafc;
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
  border-radius: 8px;
  color: rgba(148, 163, 184, 0.78);
  font-size: 12px;
  line-height: 1.2;
  padding: 9px 10px;
}

.field-prompt-message {
  font-size: 11px;
  color: #99f6e4;
  line-height: 1.35;
}

input,
select,
textarea {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  padding: 8px 9px;
  color: rgba(226, 232, 240, 0.96);
  background: rgba(2, 6, 23, 0.5);
  font: inherit;
}

textarea {
  resize: vertical;
  min-height: 98px;
}

@media (max-width: 1120px) {
  .form-grid,
  .capability-grid {
    grid-template-columns: 1fr;
  }
}
</style>
