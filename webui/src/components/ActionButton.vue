<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'default' | 'primary' | 'menu'
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
  compact?: boolean
  block?: boolean
  icon?: boolean
}>(), {
  variant: 'default',
  type: 'button',
  disabled: false,
  compact: false,
  block: false,
  icon: false,
})

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <button
    class="action-button"
    :class="[variant, { compact, block, icon }]"
    :type="type"
    :disabled="disabled"
    @click="emit('click', $event)"
  >
    <slot />
  </button>
</template>

<style scoped>
.action-button {
  min-height: var(--ui-control-height, 36px);
  padding: 0 12px;
  border: 1px solid var(--ui-button-border, rgba(148, 163, 184, 0.2));
  border-radius: var(--ui-control-radius, 8px);
  background: var(--ui-button-background, #1e293b);
  color: var(--ui-button-text, #f1f5f9);
  font: inherit;
  cursor: pointer;
  transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
}

.action-button.compact {
  min-height: var(--ui-control-height-compact, 32px);
  padding-inline: 10px;
  font-size: 12px;
}

.action-button.block {
  width: 100%;
}

.action-button.icon {
  display: grid;
  width: 34px;
  min-width: 34px;
  height: 34px;
  place-items: center;
  padding: 0;
}

.action-button.icon.compact {
  width: 28px;
  min-width: 28px;
  height: 28px;
  min-height: 28px;
  padding: 0;
}

.action-button.menu {
  display: block;
  width: 100%;
  min-height: 0;
  padding: 6px 8px;
  border-color: transparent;
  background: transparent;
  text-align: left;
}

.action-button.primary {
  border-color: var(--ui-primary-border, #3b82f6);
  background: var(--ui-primary-background, rgba(59, 130, 246, 0.12));
  color: var(--ui-primary-text, #93c5fd);
}

.action-button:hover:not(:disabled) {
  border-color: var(--ui-button-hover-border, rgba(148, 163, 184, 0.25));
  background: var(--ui-button-hover-background, #334155);
  box-shadow: none;
  transform: none;
}

.action-button.primary:hover:not(:disabled) {
  border-color: var(--ui-primary-border, #3b82f6);
  background: var(--ui-primary-hover-background, rgba(59, 130, 246, 0.2));
}

.action-button:active:not(:disabled) {
  transform: scale(0.98);
}

.action-button.menu:active:not(:disabled) {
  transform: none;
}

.action-button:focus-visible {
  outline: 2px solid var(--ui-control-focus, #3b82f6);
  outline-offset: 2px;
}

.action-button:disabled {
  cursor: default;
  opacity: 0.5;
}
</style>
