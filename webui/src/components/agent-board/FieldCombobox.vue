<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { NodeSchemaOption } from '../../composables/nodeSchemaFields'

const props = defineProps<{
  id: string
  value: string
  options: NodeSchemaOption[]
  resetKey?: string
}>()

const emit = defineEmits<{
  'update-value': [value: string]
}>()

const open = ref(false)
const searchQuery = ref('')
const listboxId = computed(() => `${props.id}-options`)
const normalizedQuery = computed(() => searchQuery.value.trim().toLocaleLowerCase())
const filteredOptions = computed(() => {
  if (!normalizedQuery.value) return props.options
  return props.options.filter((option) => (
    option.value.toLocaleLowerCase().includes(normalizedQuery.value)
    || option.label.toLocaleLowerCase().includes(normalizedQuery.value)
  ))
})

watch(() => props.resetKey, closeMenu)

function openMenu(event?: FocusEvent | MouseEvent) {
  const wasOpen = open.value
  open.value = true
  if (!wasOpen) {
    searchQuery.value = ''
    const input = event?.currentTarget
    if (input instanceof HTMLInputElement && props.options.some((option) => option.value === props.value)) {
      input.select()
    }
  }
}

function closeMenu() {
  open.value = false
  searchQuery.value = ''
}

function toggleMenu() {
  if (open.value) closeMenu()
  else open.value = true
}

function updateValue(value: string) {
  searchQuery.value = value
  open.value = true
  emit('update-value', value)
}

function selectOption(option: NodeSchemaOption) {
  emit('update-value', option.value)
  closeMenu()
}

function handleFocusOut(event: FocusEvent) {
  const nextTarget = event.relatedTarget
  const currentTarget = event.currentTarget
  if (
    currentTarget instanceof HTMLElement
    && nextTarget instanceof Node
    && currentTarget.contains(nextTarget)
  ) return
  closeMenu()
}
</script>

<template>
  <div class="field-combobox" @focusout="handleFocusOut">
    <div class="field-combobox-control">
      <input
        :id="id"
        class="field-input field-combobox-input"
        type="text"
        role="combobox"
        autocomplete="off"
        :aria-expanded="open"
        :aria-controls="listboxId"
        :value="value"
        @focus="openMenu"
        @click="openMenu"
        @keydown.escape.prevent="closeMenu"
        @input="updateValue(($event.target as HTMLInputElement).value)"
      />
      <button
        class="field-combobox-toggle"
        type="button"
        :aria-label="open ? 'Close options' : 'Open options'"
        @mousedown.prevent
        @click.stop="toggleMenu"
      >
        ▾
      </button>
    </div>
    <div v-if="open" :id="listboxId" class="field-combobox-menu" role="listbox">
      <button
        v-for="option in filteredOptions"
        :key="option.value"
        class="field-combobox-option"
        :class="{ selected: option.value === value }"
        type="button"
        role="option"
        :aria-selected="option.value === value"
        @mousedown.prevent
        @click="selectOption(option)"
      >
        <span>{{ option.label }}</span>
        <small v-if="option.label !== option.value">{{ option.value }}</small>
      </button>
      <span v-if="filteredOptions.length === 0" class="field-combobox-empty">No matching options.</span>
    </div>
  </div>
</template>

<style scoped>
.field-combobox {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-combobox-control {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
}

.field-combobox-input {
  border-radius: 7px 0 0 7px;
}

.field-combobox-toggle {
  width: 34px;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.25));
  border-left: 0;
  border-radius: 0 7px 7px 0;
  color: var(--theme-panel-node-side-editor-text-secondary, #cbd5e1);
  background: var(--theme-panel-node-side-editor-input-background, rgba(15, 23, 42, 0.82));
  cursor: pointer;
}

.field-combobox-menu {
  display: flex;
  flex-direction: column;
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.25));
  border-radius: 7px;
  background: var(--theme-panel-node-side-editor-input-background, #0f172a);
}

.field-combobox-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 7px 9px;
  border: 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  color: var(--theme-panel-node-side-editor-text-primary, #e2e8f0);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.field-combobox-option:last-child {
  border-bottom: 0;
}

.field-combobox-option:hover,
.field-combobox-option.selected {
  background: rgba(56, 189, 248, 0.14);
}

.field-combobox-option small,
.field-combobox-empty {
  color: var(--theme-panel-node-side-editor-text-muted, #94a3b8);
  font-size: 11px;
}

.field-combobox-empty {
  padding: 9px;
}
</style>
