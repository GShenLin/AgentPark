<script setup lang="ts">
withDefaults(defineProps<{
  disabled?: boolean
  icon?: boolean
  compact?: boolean
  variant?: 'default' | 'menu'
  ariaLabel?: string
}>(), {
  disabled: false,
  icon: false,
  compact: false,
  variant: 'default',
})

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <button
    class="danger-button"
    :class="[variant, { icon, compact }]"
    type="button"
    :disabled="disabled"
    :aria-label="ariaLabel"
    @click="emit('click', $event)"
  >
    <slot>Delete</slot>
  </button>
</template>

<style scoped>
.danger-button {
  min-height: var(--ui-control-height, 36px);
  padding: 0 12px;
  border: 1px solid var(--ui-danger-border, rgba(248, 113, 113, 0.48));
  border-radius: var(--ui-control-radius, 8px);
  background: var(--ui-danger-background, rgba(127, 29, 29, 0.2));
  color: var(--ui-danger-text, #fecaca);
  font: inherit;
  cursor: pointer;
  transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
}

.danger-button.icon {
  display: grid;
  place-items: center;
  width: 34px;
  min-width: 34px;
  height: 34px;
  padding: 0;
  font-size: 18px;
}

.danger-button.compact:not(.icon) {
  min-height: var(--ui-control-height-compact, 32px);
  padding-inline: 10px;
  font-size: 12px;
}

.danger-button.icon.compact {
  width: 28px;
  min-width: 28px;
  height: 28px;
  min-height: 28px;
  font-size: 14px;
}

.danger-button.menu {
  display: block;
  width: 100%;
  min-height: 0;
  padding: 6px 8px;
  border-color: transparent;
  background: transparent;
  text-align: left;
}

.danger-button:hover:not(:disabled) {
  border-color: var(--ui-danger-hover-border, rgba(252, 165, 165, 0.86));
  background: var(--ui-danger-hover-background, rgba(185, 28, 28, 0.42));
  box-shadow: none;
  transform: none;
}

.danger-button:active:not(:disabled) {
  transform: scale(0.97);
}

.danger-button.menu:active:not(:disabled) {
  transform: none;
}

.danger-button:focus-visible {
  outline: 2px solid rgba(252, 165, 165, 0.82);
  outline-offset: 2px;
}

.danger-button:disabled {
  cursor: default;
  opacity: 0.5;
}
</style>
