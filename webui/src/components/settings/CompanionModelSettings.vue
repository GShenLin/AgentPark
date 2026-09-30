<script setup lang="ts">
import { computed } from 'vue'
import type { ProviderInfo } from '../../api'
import { providerModelIds, providerReasoningEffortOptions } from '../../composables/useAgentNodeCreateSchema'
import ProviderSelect from '../ProviderSelect.vue'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'

const props = defineProps<{ data: Record<string, unknown>; providers: ProviderInfo[] }>()
const emit = defineEmits<{ 'update:data': [value: Record<string, unknown>] }>()
const providerOptions = computed(() => props.providers
  .filter(provider => provider.supportmode.includes('chat'))
  .map(provider => provider.id).sort((a, b) => a.localeCompare(b)))
const selectedProvider = computed(() => props.providers.find(provider => provider.id === props.data.provider_id))
const models = computed(() => providerModelIds(selectedProvider.value))
const invalidModel = computed(() => !!value('model') && !models.value.includes(value('model')))
const reasoningOptions = computed(() => [
  { value: '', label: 'Unset' }, ...providerReasoningEffortOptions(selectedProvider.value),
])

function value(key: string) { return String(props.data[key] ?? '') }
function setField(key: string, selected: string) {
  const next = { ...props.data, [key]: selected }
  if (!selected) delete next[key]
  if (key === 'provider_id') {
    const provider = props.providers.find(item => item.id === selected)
    if (!providerModelIds(provider).includes(String(next.model || ''))) delete next.model
    const efforts = provider?.features?.reasoning_effort
    if (!efforts?.supported || !efforts.values?.includes(String(next.reasoning_effort || ''))) {
      delete next.reasoning_effort
    }
  }
  emit('update:data', next)
}
</script>

<template>
  <div class="form-grid">
    <label>
      <span>Provider ID</span>
      <ProviderSelect :model-value="value('provider_id')" :providers="providers" :option-ids="providerOptions"
        placeholder="Select Provider ID" @change="setField('provider_id', $event)" />
    </label>
    <label>
      <span>Model ID</span>
      <FormSelect :model-value="value('model')" :disabled="!selectedProvider" @change="setField('model', $event)">
        <option value="" disabled>Select Model ID</option>
        <option v-if="invalidModel" :value="value('model')" disabled>{{ value('model') }} (unavailable)</option>
        <option v-for="model in models" :key="model" :value="model">{{ model }}</option>
      </FormSelect>
      <span v-if="selectedProvider && !models.length" class="error">This Provider has no configured models.</span>
      <span v-else-if="invalidModel" class="error">Select a model allowed by this Provider.</span>
    </label>
    <label>
      <span>Mode</span>
      <FormSelect :model-value="value('mode') || 'chat'" @change="setField('mode', $event)">
        <option v-for="mode in ['chat', 'vision_understand']" :key="mode" :value="mode">{{ mode }}</option>
      </FormSelect>
    </label>
    <label v-for="field in [{ key: 'web_search', label: 'Web Search' }, { key: 'thinking', label: 'Thinking' }]" :key="field.key">
      <span>{{ field.label }}</span>
      <FormSelect :model-value="value(field.key) || 'disabled'" @change="setField(field.key, $event)">
        <option value="disabled">disabled</option><option value="enabled">enabled</option>
      </FormSelect>
    </label>
    <label>
      <span>Reasoning Effort</span>
      <FormSelect :model-value="value('reasoning_effort')" @change="setField('reasoning_effort', $event)">
        <option v-for="option in reasoningOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
      </FormSelect>
    </label>
    <label>
      <span>Working Path</span>
      <FormTextInput :model-value="value('working_path')" @update:model-value="setField('working_path', $event)" />
    </label>
  </div>
  <p class="help">Select both IDs. Startup recovery uses this model to repair AgentPark, then rebuilds and checks server readiness.</p>
</template>

<style scoped>
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 12px; }
label { display: flex; flex-direction: column; gap: 5px; color: rgba(226, 232, 240, 0.94); font-size: 12px; }
.help { font-size: 12px; color: #94a3b8; margin: 10px 0 0; }
.error { color: #fca5a5; }
@media (max-width: 1120px) { .form-grid { grid-template-columns: 1fr; } }
</style>
