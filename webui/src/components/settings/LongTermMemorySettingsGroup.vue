<script setup lang="ts">
import { computed } from 'vue'
import { t } from '../../i18n'
import { memoryNumericFields, type LongTermMemorySettings } from '../../longTermMemorySettings'
import FormSelect from '../FormSelect.vue'
import AgentInferenceProfileSelect from './AgentInferenceProfileSelect.vue'
import FormTextInput from '../FormTextInput.vue'

const props = defineProps<{
  data: Record<string, unknown>
  defaults?: LongTermMemorySettings
}>()
const emit = defineEmits<{ 'update:data': [value: Record<string, unknown>] }>()
const effective = computed(() => props.defaults ? { ...props.defaults, ...props.data } : null)
const profileKeys = ['extract_profile_id', 'consolidation_profile_id'] as const

function setField(key: keyof LongTermMemorySettings, value: unknown) {
  emit('update:data', { ...props.data, [key]: value })
}

function setNumber(key: keyof LongTermMemorySettings, text: string) {
  // Blank restores the server's default. Invalid numeric input is rejected on save.
  if (!text.trim()) {
    const next = { ...props.data }
    delete next[key]
    emit('update:data', next)
    return
  }
  setField(key, Number(text))
}
</script>

<template>
  <section id="long-term-memory-settings" class="settings-group memory-settings">
    <h2>{{ t('longMemory.title') }}</h2>
    <p>{{ t('longMemory.description') }}</p>
    <p class="help">{{ t('longMemory.effect') }}</p>
    <p v-if="!effective" role="alert">{{ t('longMemory.unavailable') }}</p>
    <template v-else>
      <div class="memory-grid">
        <label>
          <span>{{ t('longMemory.enabled') }}</span>
          <FormSelect :model-value="String(effective.enabled)" @update:model-value="setField('enabled', $event === 'true')">
            <option value="true">{{ t('longMemory.on') }}</option>
            <option value="false">{{ t('longMemory.off') }}</option>
          </FormSelect>
          <small>{{ t('longMemory.enabledHelp') }}</small>
        </label>
        <label v-for="key in profileKeys" :key="key">
          <span>{{ t(`longMemory.${key}`) }}</span>
          <AgentInferenceProfileSelect :model-value="String(effective[key])" @update:model-value="setField(key, $event)" />
          <small>{{ t(`longMemory.${key}Help`) }}</small>
        </label>
        <label v-for="field in memoryNumericFields.filter(field => !field.advanced)" :key="field.key">
          <span>{{ t(`longMemory.${field.key}`) }}</span>
          <FormTextInput :model-value="String(effective[field.key])" type="number" :min="field.min" step="1"
            @update:model-value="setNumber(field.key, $event)" />
          <small>{{ t(`longMemory.${field.key}Help`) }}</small>
        </label>
      </div>
      <details>
        <summary>{{ t('longMemory.advanced') }}</summary>
        <div class="memory-grid">
          <label v-for="field in memoryNumericFields.filter(field => field.advanced)" :key="field.key">
            <span>{{ t(`longMemory.${field.key}`) }}</span>
            <FormTextInput :model-value="String(effective[field.key])" type="number" :min="field.min" step="1"
              @update:model-value="setNumber(field.key, $event)" />
            <small>{{ t(`longMemory.${field.key}Help`) }}</small>
          </label>
        </div>
      </details>
    </template>
  </section>
</template>

<style scoped>
.memory-settings { border: 1px solid var(--border-subtle); border-radius: 8px; padding: 16px; }
h2 { margin: 0 0 10px; font-size: 16px; }
p { margin: 6px 0; line-height: 1.5; }
.help, small { color: var(--text-secondary); }
.memory-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 16px; }
label { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
small { line-height: 1.5; }
details { margin-top: 18px; }
summary { cursor: pointer; }
[role="alert"] { color: var(--accent-red, #f87171); }
@media (max-width: 800px) { .memory-grid { grid-template-columns: 1fr; } }
</style>
