<script setup lang="ts">
type DisplayOption = {
  value: string
  title: string
  description: string
  meta: string
  sourceLabel: string
  statusLabel: string
  statusClass: string
  dependencySummary: string
  diagnosticLines: string[]
  nextRunLabel: string
}

const props = defineProps<{
  option: DisplayOption
  selected: boolean
  diagnosticKeyPrefix: string
}>()

const emit = defineEmits<{
  toggle: [value: string]
}>()

function toggle() {
  emit('toggle', props.option.value)
}
</script>

<template>
  <div
    class="multi-select-option"
    :class="{ 'is-selected': selected }"
    role="checkbox"
    tabindex="0"
    :aria-checked="selected ? 'true' : 'false'"
    @click="toggle"
    @keydown.enter.prevent="toggle"
    @keydown.space.prevent="toggle"
  >
    <input
      type="checkbox"
      :checked="selected"
      tabindex="-1"
      @click.stop="toggle"
      @change.stop
    />
    <span class="multi-select-copy">
      <span class="multi-select-title">{{ option.title }}</span>
      <span
        v-if="option.sourceLabel || option.statusLabel || option.nextRunLabel"
        class="multi-select-badges"
      >
        <span v-if="option.sourceLabel" class="multi-select-badge">{{ option.sourceLabel }}</span>
        <span
          v-if="option.statusLabel"
          class="multi-select-badge"
          :class="option.statusClass"
        >{{ option.statusLabel }}</span>
        <span v-if="option.nextRunLabel" class="multi-select-badge is-next-run">{{ option.nextRunLabel }}</span>
      </span>
      <span v-if="option.description" class="multi-select-description">{{ option.description }}</span>
      <span v-else-if="option.meta" class="multi-select-meta">{{ option.meta }}</span>
      <span v-if="option.dependencySummary" class="multi-select-meta">{{ option.dependencySummary }}</span>
      <span
        v-for="diagnostic in option.diagnosticLines"
        :key="`${diagnosticKeyPrefix}-${option.value}-${diagnostic}`"
        class="multi-select-diagnostic"
      >{{ diagnostic }}</span>
    </span>
  </div>
</template>

<style scoped>
.multi-select-option {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.2);
  padding: 8px;
  font-size: 12px;
  color: rgba(226, 232, 240, 0.95);
  line-height: 1.3;
  cursor: pointer;
}

.multi-select-option:hover,
.multi-select-option:focus-visible {
  border-color: rgba(56, 189, 248, 0.55);
  background: rgba(14, 116, 144, 0.14);
  outline: none;
}

.multi-select-option.is-selected {
  border-color: rgba(56, 189, 248, 0.46);
  background: rgba(8, 47, 73, 0.55);
}

.multi-select-option input {
  flex: 0 0 auto;
  width: 14px;
  height: 14px;
  margin: 0;
  accent-color: #38bdf8;
}

.multi-select-copy {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.multi-select-title {
  color: #f8fafc;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.multi-select-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}

.multi-select-badge {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.76);
  color: rgba(203, 213, 225, 0.82);
  font-size: 10px;
  line-height: 1.1;
  max-width: 100%;
  overflow: hidden;
  padding: 2px 5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.multi-select-badge.is-selected-status {
  border-color: rgba(45, 212, 191, 0.34);
  color: #99f6e4;
}

.multi-select-badge.is-error,
.multi-select-badge.is-unavailable {
  border-color: rgba(248, 113, 113, 0.42);
  color: #fecaca;
}

.multi-select-badge.is-next-run {
  border-color: rgba(250, 204, 21, 0.36);
  color: #fde68a;
}

.multi-select-description,
.multi-select-meta {
  color: rgba(203, 213, 225, 0.72);
  display: -webkit-box;
  overflow: hidden;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.multi-select-meta {
  color: rgba(148, 163, 184, 0.72);
}

.multi-select-diagnostic {
  color: #fecaca;
  display: -webkit-box;
  overflow: hidden;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
</style>
