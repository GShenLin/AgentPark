<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  value: string
  defaultColor?: string
  autoLabel?: string
}>(), {
  defaultColor: '#FFFFFF',
  autoLabel: 'Auto',
})

const emit = defineEmits<{
  'update-value': [value: string]
}>()

const HEX_COLOR_PATTERN = /^#[0-9A-F]{6}$/

function normalizeColor(value: unknown) {
  const color = String(value || '').trim().toUpperCase()
  return HEX_COLOR_PATTERN.test(color) ? color : ''
}

const selectedColor = computed(() => normalizeColor(props.value))
const pickerColor = computed(() => (
  selectedColor.value
  || normalizeColor(props.defaultColor)
  || '#FFFFFF'
))
const isAuto = computed(() => !selectedColor.value)

function selectColor(event: Event) {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  const color = normalizeColor(target.value)
  if (color) emit('update-value', color)
}

function selectAuto() {
  emit('update-value', '')
}
</script>

<template>
  <div class="color-picker-field">
    <input
      class="color-picker-input"
      type="color"
      :value="pickerColor"
      aria-label="Pick background color"
      @input="selectColor"
    />
    <span class="color-picker-value">{{ isAuto ? 'Corners' : selectedColor }}</span>
    <button
      class="color-picker-auto"
      :class="{ 'color-picker-auto-active': isAuto }"
      type="button"
      :aria-pressed="isAuto"
      @click="selectAuto"
    >
      {{ autoLabel }}
    </button>
  </div>
</template>

<style scoped>
.color-picker-field {
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.color-picker-input {
  width: 46px;
  height: 38px;
  box-sizing: border-box;
  border: 1px solid var(--theme-panel-node-side-editor-input-border, rgba(148, 163, 184, 0.22));
  border-radius: 10px;
  background: var(--theme-panel-node-side-editor-input-background, rgba(15, 23, 42, 0.88));
  cursor: pointer;
  padding: 4px;
}

.color-picker-input::-webkit-color-swatch-wrapper {
  padding: 0;
}

.color-picker-input::-webkit-color-swatch {
  border: 0;
  border-radius: 6px;
}

.color-picker-value {
  min-width: 0;
  color: var(--theme-panel-node-side-editor-input-text, #f8fafc);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.color-picker-auto {
  height: 34px;
  border: 1px solid var(--theme-panel-node-side-editor-button-border, rgba(148, 163, 184, 0.28));
  border-radius: 9px;
  background: var(--theme-panel-node-side-editor-button-background, rgba(15, 23, 42, 0.92));
  color: var(--theme-panel-node-side-editor-button-text, #f8fafc);
  cursor: pointer;
  font-size: 11px;
  padding: 0 10px;
}

.color-picker-auto-active {
  border-color: rgba(45, 212, 191, 0.62);
  background: rgba(13, 148, 136, 0.28);
  color: #99f6e4;
}
</style>
