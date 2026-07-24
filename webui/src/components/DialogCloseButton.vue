<script setup lang="ts">
withDefaults(
  defineProps<{
    ariaLabel?: string
  }>(),
  {
    ariaLabel: 'Close',
  },
)

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <button
    class="dialog-close-button"
    type="button"
    :aria-label="ariaLabel"
    title="Close"
    @click="emit('click', $event)"
  >
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  </button>
</template>

<style scoped>
.dialog-close-button {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid rgba(248, 113, 113, 0.72);
  border-radius: 8px;
  background: rgba(127, 29, 29, 0.72);
  color: rgba(254, 226, 226, 0.98);
  cursor: pointer;
  transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
}

.dialog-close-button:hover {
  border-color: rgba(252, 165, 165, 0.94);
  background: rgba(185, 28, 28, 0.88);
}

.dialog-close-button:active {
  transform: scale(0.94);
}

.dialog-close-button:focus-visible {
  outline: 2px solid rgba(252, 165, 165, 0.92);
  outline-offset: 2px;
}

.dialog-close-button svg {
  display: block;
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-width: 1.8;
}
</style>
