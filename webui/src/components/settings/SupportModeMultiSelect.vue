<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  selectedValues: string[]
}>()

const emit = defineEmits<{
  'update:selectedValues': [value: string[]]
}>()

const options = computed(() => {
  const defaults = [
    'chat',
    'imagechat',
    'image_generation',
    'vision_understand',
    'GUIAgent',
    'video_generation',
    'video_change_person',
    'model_generation',
    'model_texture_generation',
  ]
  return Array.from(new Set([...defaults, ...props.selectedValues])).filter(Boolean)
})

const summary = computed(() => props.selectedValues.join(', ') || 'Select support modes')

function toggle(value: string) {
  const item = String(value || '').trim()
  if (!item) return
  const next = props.selectedValues.includes(item)
    ? props.selectedValues.filter((entry) => entry !== item)
    : [...props.selectedValues, item]
  emit('update:selectedValues', next)
}
</script>

<template>
  <details class="multi-dropdown">
    <summary>{{ summary }}</summary>
    <div class="multi-dropdown-menu">
      <label v-for="mode in options" :key="mode" class="multi-option">
        <input
          type="checkbox"
          :checked="selectedValues.includes(mode)"
          @change="toggle(mode)"
        />
        <span>{{ mode }}</span>
      </label>
    </div>
  </details>
</template>

<style scoped>
.multi-dropdown {
  position: relative;
  width: 100%;
}

.multi-dropdown summary {
  min-height: 34px;
  display: flex;
  align-items: center;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  padding: 8px 9px;
  color: rgba(226, 232, 240, 0.96);
  background: rgba(2, 6, 23, 0.5);
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.multi-dropdown-menu {
  position: absolute;
  z-index: 10;
  top: calc(100% + 4px);
  left: 0;
  width: 100%;
  max-height: 240px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  padding: 8px;
  background: rgba(2, 6, 23, 0.98);
  box-shadow: 0 14px 32px rgba(0, 0, 0, 0.35);
}

.multi-option {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  padding: 5px 4px;
  color: rgba(226, 232, 240, 0.94);
  font-size: 12px;
}

.multi-option input {
  width: 14px;
  height: 14px;
  margin: 0;
  accent-color: #38bdf8;
}
</style>
