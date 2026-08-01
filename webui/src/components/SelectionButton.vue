<script setup lang="ts">
withDefaults(defineProps<{
  active?: boolean
  disabled?: boolean
  stacked?: boolean
}>(), {
  active: false,
  disabled: false,
  stacked: false,
})

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <button
    class="selection-button"
    :class="{ active, stacked }"
    type="button"
    :disabled="disabled"
    :aria-pressed="active"
    @click="emit('click', $event)"
  >
    <span class="selection-button__label"><slot /></span>
    <span v-if="$slots.detail" class="selection-button__detail"><slot name="detail" /></span>
  </button>
</template>

<style scoped>
.selection-button {
  box-sizing: border-box;
  width: 100%;
  min-height: var(--ui-selection-height, 36px);
  display: flex;
  align-items: center;
  padding: 0 12px;
  border: 1px solid var(--ui-selection-border, transparent);
  border-radius: var(--ui-selection-radius, var(--ui-control-radius, 8px));
  background: var(--ui-selection-background, transparent);
  color: var(--ui-selection-text, var(--ui-button-text, #f1f5f9));
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: border-color 120ms ease, background 120ms ease, color 120ms ease;
  backdrop-filter: none;
}

.selection-button.stacked {
  min-height: var(--ui-selection-stacked-height, 48px);
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 1px;
  padding: 6px 12px;
}

.selection-button:hover:not(:disabled) {
  border-color: var(--ui-selection-hover-border, var(--ui-selection-border, transparent));
  background: var(--ui-selection-hover-background, var(--ui-button-hover-background, #334155));
  color: var(--ui-selection-hover-text, var(--ui-selection-text, #f1f5f9));
  box-shadow: none;
  transform: none;
}

.selection-button.active {
  border-color: var(--ui-selection-active-border, var(--ui-primary-border, #3b82f6));
  background: var(--ui-selection-active-background, var(--ui-primary-background, rgba(59, 130, 246, 0.12)));
  color: var(--ui-selection-active-text, var(--ui-primary-text, #93c5fd));
}

.selection-button:active:not(:disabled) {
  transform: none;
}

.selection-button:focus,
.selection-button:focus-visible {
  outline: 2px solid var(--ui-control-focus, #3b82f6);
  outline-offset: -2px;
}

.selection-button:disabled {
  cursor: default;
  opacity: 0.5;
}

.selection-button__label,
.selection-button__detail {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selection-button.stacked .selection-button__label {
  font-weight: 650;
}

.selection-button__detail {
  color: var(--ui-selection-detail-text, var(--text-secondary, #94a3b8));
  font-size: 11px;
  font-weight: 400;
}
</style>
