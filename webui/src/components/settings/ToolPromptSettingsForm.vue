<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { t } from '../../i18n'
import { MAX_TOOL_PROMPT_CHARS, readToolPrompts, setToolPrompt, toolPromptEntries, validToolPromptName, type ToolPromptDefinition } from '../../toolPromptEditor'
import ActionButton from '../ActionButton.vue'
import SelectionButton from '../SelectionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import ExpandableTextarea from '../ExpandableTextarea.vue'

const props = defineProps<{ data: Record<string, unknown>; catalog: ToolPromptDefinition[] }>()
const emit = defineEmits<{ 'update:data': [data: Record<string, unknown>] }>()
const selected = ref('execute_console_command'), query = ref(''), newName = ref('')
const overrides = computed(() => readToolPrompts(props.data))
const entries = computed(() => toolPromptEntries(props.catalog, overrides.value || {}))
const filtered = computed(() => entries.value.filter(item => item.name.toLowerCase().includes(query.value.trim().toLowerCase())))
const current = computed(() => entries.value.find(item => item.name === selected.value))
const customized = computed(() => !!overrides.value && Object.prototype.hasOwnProperty.call(overrides.value, selected.value))
const value = computed(() => customized.value ? overrides.value![selected.value]! : current.value?.defaults[0]?.description || '')
const canAdd = computed(() => !!overrides.value && validToolPromptName(newName.value)
  && !entries.value.some(item => item.name === newName.value))
watch(entries, items => {
  if (!items.some(item => item.name === selected.value)) selected.value = items[0]?.name || ''
}, { immediate: true })
function update(prompt: string | null) {
  emit('update:data', setToolPrompt(props.data, selected.value, prompt))
}
function add() {
  if (!canAdd.value) return
  const name = newName.value
  emit('update:data', setToolPrompt(props.data, name, ''))
  selected.value = name
  query.value = ''
  newName.value = ''
}
</script>

<template>
  <section class="prompt-settings">
    <h2>{{ t('toolprompts.title') }}</h2>
    <p class="intro">{{ t('toolprompts.intro') }}</p>
    <p v-if="!overrides" role="alert">{{ t('toolprompts.invalid') }}</p>
    <template v-else>
      <form class="add-prompt" @submit.prevent="add">
        <FormTextInput v-model="newName" :placeholder="t('toolprompts.namePlaceholder')" :aria-label="t('toolprompts.name')" />
        <ActionButton compact :disabled="!canAdd" @click="add">{{ t('toolprompts.add') }}</ActionButton>
      </form>
      <p class="hint">{{ t('toolprompts.externalHint') }}</p>
      <div class="prompt-columns">
        <div class="prompt-browser">
          <FormTextInput v-model="query" type="search" :placeholder="t('toolprompts.search')" :aria-label="t('toolprompts.search')" />
          <nav class="prompt-list" :aria-label="t('toolprompts.tools')">
            <SelectionButton v-for="item in filtered" :key="item.name" :active="selected === item.name" @click="selected = item.name">
              <span class="tool-name">{{ item.name }}</span>
              <template #detail><small v-if="Object.prototype.hasOwnProperty.call(overrides, item.name)">{{ t('toolprompts.custom') }}</small></template>
            </SelectionButton>
            <p v-if="!filtered.length" class="hint">{{ t('toolsets.noMatches') }}</p>
          </nav>
        </div>
        <div v-if="current" class="prompt-editor">
          <header>
            <div><h3>{{ current.name }}</h3><span class="hint">{{ t(customized ? 'toolprompts.custom' : 'toolprompts.default') }}</span></div>
            <ActionButton compact :disabled="!customized" @click="update(null)">{{ t('toolprompts.restore') }}</ActionButton>
          </header>
          <label class="editor-label">
            <span>{{ t('toolprompts.description') }}</span>
            <ExpandableTextarea :model-value="value" :rows="12" :max-length="MAX_TOOL_PROMPT_CHARS" min-height="260px" max-height="480px"
              :title="t('toolprompts.description')" :aria-label="t('toolprompts.description')" @update:model-value="update" />
          </label>
          <span class="hint">{{ value.length }} / {{ MAX_TOOL_PROMPT_CHARS }}</span>
          <p v-if="current.defaults.length > 1" class="hint">{{ t('toolprompts.sharedName') }}</p>
          <details v-if="current.defaults.length" class="default-preview">
            <summary>{{ t('toolprompts.viewDefault') }}</summary>
            <div v-for="item in current.defaults" :key="item.source"><code>{{ item.source }}</code><pre>{{ item.description }}</pre></div>
          </details>
          <p v-else class="hint">{{ t('toolprompts.externalDefault') }}</p>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.prompt-settings { padding: 20px; }
h2 { margin: 0 0 10px; font-size: 18px; }
.intro, .hint { color: var(--text-secondary); line-height: 1.65; }
.intro { max-width: 960px; }
.hint { font-size: 12px; }
.add-prompt { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.add-prompt :deep(input) { min-width: 260px; }
.prompt-columns { display: grid; grid-template-columns: minmax(200px, 300px) minmax(0, 1fr); gap: 24px; margin-top: 20px; }
.prompt-browser { display: grid; align-content: start; gap: 10px; min-width: 0; }
.prompt-list { display: flex; flex-direction: column; gap: 5px; max-height: 62vh; overflow: auto; }
.tool-name, h3 { overflow-wrap: anywhere; font-family: var(--font-mono, monospace); }
.prompt-editor { min-width: 0; display: grid; align-content: start; gap: 12px; }
header { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
h3 { margin: 0 0 4px; font-size: 15px; }
.editor-label { display: grid; gap: 8px; font-size: 13px; }
.default-preview { border: 1px solid var(--border-subtle); border-radius: 10px; padding: 14px; }
summary { cursor: pointer; }
.default-preview code { display: block; margin-top: 14px; color: var(--text-secondary); overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; font-size: 13px; line-height: 1.65; }
@media (max-width: 760px) {
  .prompt-columns { grid-template-columns: minmax(0, 1fr); }
  .prompt-list { max-height: 220px; }
  .prompt-settings { padding: 12px; }
}
</style>
