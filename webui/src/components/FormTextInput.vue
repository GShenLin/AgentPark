<script setup lang="ts">
import { ref } from 'vue'

defineOptions({ inheritAttrs: false })

withDefaults(defineProps<{
  modelValue: string | number
  type?: 'text' | 'number' | 'password' | 'date' | 'search' | 'email' | 'url' | 'tel'
  disabled?: boolean
  readonly?: boolean
  compact?: boolean
}>(), {
  type: 'text',
  disabled: false,
  readonly: false,
  compact: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  change: [value: string]
}>()

const inputRef = ref<HTMLInputElement | null>(null)

function focus() {
  inputRef.value?.focus()
}

function select() {
  inputRef.value?.select()
}

function blur() {
  inputRef.value?.blur()
}

function update(event: Event) {
  emit('update:modelValue', (event.target as HTMLInputElement).value)
}

function change(event: Event) {
  emit('change', (event.target as HTMLInputElement).value)
}

defineExpose({ focus, select, blur, input: inputRef })
</script>

<template>
  <input
    ref="inputRef"
    v-bind="$attrs"
    class="form-text-input"
    :class="{ compact }"
    :type="type"
    :value="modelValue"
    :disabled="disabled"
    :readonly="readonly"
    @input="update"
    @change="change"
  />
</template>

<style scoped>
.form-text-input {
  width: 100%;
  min-height: var(--ui-control-height, 36px);
  box-sizing: border-box;
  padding: 7px var(--ui-control-padding-x, 10px);
  border: 1px solid var(--form-control-border, var(--ui-control-border, rgba(148, 163, 184, 0.28)));
  border-radius: var(--ui-control-radius, 8px);
  color: var(--form-control-text, var(--ui-control-text, inherit));
  background: var(--form-control-background, var(--ui-control-background, rgba(15, 23, 42, 0.66)));
  font: inherit;
}

.form-text-input:focus {
  outline: 1px solid var(--form-control-focus, var(--ui-control-focus, #38bdf8));
  border-color: var(--form-control-focus, var(--ui-control-focus, #38bdf8));
}

.form-text-input.compact {
  min-height: 32px;
  padding: 6px 9px;
  font-size: 12px;
}

.form-text-input:disabled,
.form-text-input:read-only {
  opacity: 0.65;
}
</style>
