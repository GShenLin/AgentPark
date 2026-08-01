<script setup lang="ts">
defineOptions({ inheritAttrs: false })

withDefaults(defineProps<{
  modelValue: string | number
  disabled?: boolean
  compact?: boolean
}>(), {
  disabled: false,
  compact: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  change: [value: string]
}>()

function change(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  emit('update:modelValue', value)
  emit('change', value)
}
</script>

<template>
  <select
    v-bind="$attrs"
    class="form-select"
    :class="{ compact }"
    :value="modelValue"
    :disabled="disabled"
    @change="change"
  >
    <slot />
  </select>
</template>

<style scoped>
.form-select {
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

.form-select:focus {
  outline: 1px solid var(--form-control-focus, var(--ui-control-focus, #38bdf8));
  border-color: var(--form-control-focus, var(--ui-control-focus, #38bdf8));
}

.form-select.compact {
  min-height: 32px;
  padding: 6px 9px;
  font-size: 12px;
}

.form-select:disabled {
  opacity: 0.65;
}
</style>
