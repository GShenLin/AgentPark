<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { t } from '../../i18n'
import { readToolsets, toggleTool, validToolsetId, type ToolDefinition, type Toolset } from '../../toolsetEditor'
import ActionButton from '../ActionButton.vue'
import SelectionButton from '../SelectionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import FormCheckbox from '../FormCheckbox.vue'

const props = defineProps<{ data: Record<string, unknown>; catalog: ToolDefinition[] }>()
const emit = defineEmits<{ 'update:data': [data: Record<string, unknown>] }>()
const selected = ref('system_tools')
const query = ref('')
const newName = ref('')
const creating = ref(false)
const sets = computed(() => readToolsets(props.data))
const deletedNames = computed(() => sets.value ? (props.data.deleted_toolsets as string[] | undefined) || [] : [])
const names = computed(() => Object.keys(sets.value || {}).sort())
const current = computed(() => sets.value?.[selected.value])
const canCreate = computed(() => sets.value && validToolsetId(newName.value, sets.value))
const filtered = computed(() => {
  const search = query.value.trim().toLowerCase()
  const selectedIds = new Set(current.value?.tools || [])
  return props.catalog
    .filter(tool => `${tool.name} ${tool.description} ${tool.module}`.toLowerCase().includes(search))
    .sort((a, b) => Number(selectedIds.has(b.id)) - Number(selectedIds.has(a.id)))
})
const knownIds = computed(() => new Set(props.catalog.map(tool => tool.id)))
const unknown = computed(() => current.value?.tools.filter(id => !knownIds.value.has(id)) || [])
watch(names, values => {
  if (values.length && !values.includes(selected.value)) {
    selected.value = values.includes('system_tools') ? 'system_tools' : values[0]!
  }
}, { immediate: true })

function update(set: Toolset) {
  emit('update:data', { ...props.data, toolsets: { ...sets.value, [selected.value]: set } })
}
function create() {
  if (!canCreate.value) return
  emit('update:data', {
    ...props.data,
    toolsets: { ...sets.value, [newName.value]: { description: '', tools: [] } },
    deleted_toolsets: deletedNames.value.filter(name => name !== newName.value),
  })
  selected.value = newName.value
  newName.value = ''
  creating.value = false
  query.value = ''
}
function remove() {
  if (!sets.value || !current.value) return
  if (!window.confirm(t('toolsets.deleteConfirm', { name: selected.value }))) return
  const next = { ...sets.value }
  delete next[selected.value]
  emit('update:data', {
    ...props.data,
    toolsets: next,
    deleted_toolsets: [...new Set([...deletedNames.value, selected.value])],
  })
}
</script>

<template>
  <div class="toolsets-form">
    <p class="intro">{{ t('toolsets.intro') }}</p>
    <p v-if="!sets" role="alert">{{ t('toolsets.invalid') }}</p>
    <template v-else>
      <div class="create-row">
        <ActionButton compact @click="creating = !creating">{{ t('toolsets.new') }}</ActionButton>
        <form v-if="creating" class="create-input" @submit.prevent="create">
          <FormTextInput v-model="newName" :placeholder="t('toolsets.idPlaceholder')" :aria-label="t('toolsets.id')" />
          <ActionButton compact :disabled="!canCreate" @click="create">{{ t('toolsets.create') }}</ActionButton>
          <span class="hint">{{ t('toolsets.idHint') }}</span>
        </form>
      </div>
      <div class="toolset-columns">
        <nav class="set-list" :aria-label="t('toolsets.list')">
          <SelectionButton v-for="name in names" :key="name" :active="selected === name" @click="selected = name; query = ''">
            <span class="set-name">{{ name }}</span>
            <template #detail><span class="count">{{ sets[name]?.tools.length }}</span></template>
          </SelectionButton>
        </nav>
        <div v-if="current" class="set-detail">
          <header class="detail-head">
            <div><h2>{{ selected }}</h2><span class="hint">{{ t('toolsets.count', { count: current.tools.length }) }}</span></div>
            <ActionButton compact @click="remove">{{ t('toolsets.delete') }}</ActionButton>
          </header>
          <label class="description-field">
            <span>{{ t('toolsets.description') }}</span>
            <FormTextInput :model-value="current.description" :placeholder="t('toolsets.descriptionPlaceholder')"
              @update:model-value="update({ ...current!, description: $event })" />
          </label>
          <FormTextInput v-model="query" type="search" :placeholder="t('toolsets.search')" :aria-label="t('toolsets.search')" />
          <div v-if="unknown.length" class="unknown-tools" role="alert">
            <p>{{ t('toolsets.unknown') }}</p>
            <div v-for="id in unknown" :key="id">
              <code>{{ id }}</code>
              <ActionButton compact @click="update(toggleTool(current!, id, false))">{{ t('toolsets.remove') }}</ActionButton>
            </div>
          </div>
          <div class="tool-list">
            <label v-for="tool in filtered" :key="tool.id" class="tool-row" :class="{ selected: current.tools.includes(tool.id) }">
              <FormCheckbox :model-value="current.tools.includes(tool.id)" @update:model-value="update(toggleTool(current!, tool.id, $event))" />
              <span class="tool-copy"><strong>{{ tool.name }}</strong><span class="tool-description">{{ tool.description }}</span><small>{{ tool.module }}</small></span>
            </label>
            <p v-if="!filtered.length" class="hint">{{ t('toolsets.noMatches') }}</p>
          </div>
          <p v-if="!current.tools.length" class="hint" role="status">{{ t('toolsets.empty') }}</p>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.toolsets-form { padding: 20px; min-height: 0; overflow: auto; }
.intro { margin: 0 0 18px; line-height: 1.7; color: var(--text-secondary); max-width: 900px; }
.create-row, .create-input, .detail-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.create-row { margin-bottom: 18px; }
.create-input { flex: 1; }
.create-input input { max-width: 260px; }
.hint, .count { color: var(--text-secondary); font-size: 12px; }
.toolset-columns { display: grid; grid-template-columns: minmax(180px, 240px) minmax(0, 1fr); gap: 22px; align-items: start; }
.set-list { display: flex; flex-direction: column; gap: 5px; max-height: 65vh; overflow: auto; }
.set-list button { display: flex; justify-content: space-between; gap: 8px; text-align: left; }
.set-name { overflow-wrap: anywhere; }
.set-detail { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.detail-head { justify-content: space-between; }
h2 { margin: 0 0 5px; font-size: 18px; overflow-wrap: anywhere; }
.description-field { display: grid; gap: 8px; font-size: 13px; }
.tool-list { border: 1px solid var(--border-subtle); border-radius: 10px; overflow: hidden; }
.tool-row { display: flex; align-items: flex-start; gap: 12px; padding: 14px; cursor: pointer; background: var(--bg-primary); }
.tool-row + .tool-row { border-top: 1px solid var(--border-subtle); }
.tool-row.selected { background: var(--bg-secondary); }
.tool-row input { margin-top: 3px; }
.tool-copy { display: grid; gap: 5px; min-width: 0; overflow-wrap: anywhere; }
.tool-copy strong { font-family: var(--font-mono, monospace); font-size: 13px; }
.tool-description { font-size: 12px; color: var(--text-secondary); line-height: 1.6; white-space: pre-wrap; max-height: 5em; overflow: auto; }
.tool-copy small { font-size: 11px; color: var(--text-secondary); }
.unknown-tools { border: 1px solid var(--border-subtle); padding: 12px; }
.unknown-tools > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
@media (max-width: 720px) {
  .toolsets-form { padding: 12px; }
  .toolset-columns { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .set-list { max-height: 180px; }
}
</style>
