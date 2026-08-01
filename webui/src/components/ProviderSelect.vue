<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { ProviderInfo } from '../api'

const props = withDefaults(defineProps<{
  modelValue: string
  providers: ProviderInfo[]
  optionIds?: string[]
  disabled?: boolean
  placeholder?: string
}>(), {
  disabled: false,
  placeholder: 'Select provider',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  change: [value: string]
}>()

const root = ref<HTMLElement | null>(null)
const open = ref(false)
const options = computed(() => {
  const allowed = Array.isArray(props.optionIds) ? new Set(props.optionIds) : null
  return props.providers
    .filter((provider) => !allowed || allowed.has(String(provider.id || '').trim()))
    .slice()
    .sort((left, right) => String(left.id).localeCompare(String(right.id)))
})
const selectedProvider = computed(() => (
  props.providers.find((provider) => String(provider.id || '').trim() === props.modelValue) || null
))

function toggle() {
  if (!props.disabled) open.value = !open.value
}

function select(providerId: string) {
  emit('update:modelValue', providerId)
  emit('change', providerId)
  open.value = false
}

function closeOnOutsidePointer(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) open.value = false
}

function closeOnFocusOut(event: FocusEvent) {
  if (!root.value?.contains(event.relatedTarget as Node | null)) open.value = false
}

function handleTriggerKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    open.value = false
    return
  }
  if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    open.value = true
  }
}

onMounted(() => document.addEventListener('pointerdown', closeOnOutsidePointer))
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeOnOutsidePointer))
</script>

<template>
  <div ref="root" class="provider-select" @focusout="closeOnFocusOut">
    <button
      class="provider-select__trigger"
      type="button"
      :disabled="disabled"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="toggle"
      @keydown="handleTriggerKeydown"
    >
      <span :class="{ placeholder: !selectedProvider }">
        {{ selectedProvider?.id || modelValue || placeholder }}
      </span>
      <span class="provider-select__chevron" aria-hidden="true">▾</span>
    </button>

    <div v-if="open" class="provider-select__menu" role="listbox">
      <button
        v-for="provider in options"
        :key="provider.id"
        class="provider-select__option"
        :class="{ selected: provider.id === modelValue }"
        type="button"
        role="option"
        :aria-selected="provider.id === modelValue"
        @click="select(provider.id)"
        @keydown.esc.prevent="open = false"
      >
        <span class="provider-select__id">{{ provider.id }}</span>
        <span v-if="provider.description" class="provider-select__description">
          {{ provider.description }}
        </span>
      </button>
      <div v-if="options.length === 0" class="provider-select__empty">No providers</div>
    </div>
  </div>
</template>

<style scoped>
.provider-select {
  position: relative;
  width: 100%;
}

.provider-select__trigger {
  width: 100%;
  min-height: var(--ui-control-height, 36px);
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 7px var(--ui-control-padding-x, 10px);
  border: 1px solid var(--form-control-border, var(--ui-control-border, rgba(148, 163, 184, 0.28)));
  border-radius: var(--ui-control-radius, 8px);
  color: var(--form-control-text, var(--ui-control-text, inherit));
  background: var(--form-control-background, var(--ui-control-background, rgba(15, 23, 42, 0.66)));
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.provider-select__trigger:focus-visible {
  outline: 1px solid var(--form-control-focus, var(--ui-control-focus, #38bdf8));
  border-color: var(--form-control-focus, var(--ui-control-focus, #38bdf8));
}

.provider-select__trigger:disabled {
  cursor: default;
  opacity: 0.65;
}

.provider-select__trigger .placeholder,
.provider-select__chevron {
  opacity: 0.68;
}

.provider-select__menu {
  position: absolute;
  z-index: 100;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  max-height: 320px;
  overflow-y: auto;
  padding: 5px;
  border: 1px solid var(--form-control-border, var(--ui-control-border, rgba(148, 163, 184, 0.28)));
  border-radius: var(--ui-control-radius, 8px);
  background: var(--ui-panel-background, #111827);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.32);
}

.provider-select__option {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
  padding: 8px 9px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--ui-control-text, #e5e7eb);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.provider-select__option:hover,
.provider-select__option:focus-visible {
  border-color: var(--ui-selection-hover-border, rgba(56, 189, 248, 0.3));
  background: var(--ui-selection-hover-background, rgba(51, 65, 85, 0.82));
  outline: none;
}

.provider-select__option.selected {
  border-color: var(--ui-selection-active-border, rgba(59, 130, 246, 0.7));
  background: var(--ui-selection-active-background, rgba(59, 130, 246, 0.14));
}

.provider-select__id {
  font-weight: 600;
}

.provider-select__description {
  max-height: 0;
  overflow: hidden;
  opacity: 0;
  color: var(--ui-muted-text, #94a3b8);
  font-size: 12px;
  line-height: 1.45;
  transition: max-height 140ms ease, opacity 120ms ease, margin-top 120ms ease;
}

.provider-select__option:hover .provider-select__description,
.provider-select__option:focus-visible .provider-select__description {
  max-height: 6em;
  margin-top: 4px;
  opacity: 1;
}

.provider-select__empty {
  padding: 9px;
  color: var(--ui-muted-text, #94a3b8);
  font-size: 12px;
}
</style>
