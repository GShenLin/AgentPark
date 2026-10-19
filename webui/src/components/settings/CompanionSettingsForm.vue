<script setup lang="ts">
import AgentInferenceProfileSelect from './AgentInferenceProfileSelect.vue'
import FormTextInput from '../FormTextInput.vue'

const props = defineProps<{ data: Record<string, unknown> }>()
const emit = defineEmits<{ 'update:data': [value: Record<string, unknown>] }>()

function setField(key: 'profile_id' | 'working_path', value: string) {
  emit('update:data', { ...props.data, [key]: value })
}
</script>

<template>
  <section class="companion-form">
    <label>
      <span>Preset</span>
      <AgentInferenceProfileSelect :model-value="String(data.profile_id ?? '')"
        @update:model-value="setField('profile_id', $event)" />
    </label>
    <p>Model, instructions and capabilities are managed in Node Preset Editor.
      Companion conversations and startup recovery use the selected Preset.</p>
    <label>
      <span>Working Path</span>
      <FormTextInput :model-value="String(data.working_path ?? '')"
        @update:model-value="setField('working_path', $event)" />
    </label>
  </section>
</template>

<style scoped>
.companion-form { display: flex; flex-direction: column; gap: 12px; max-width: 720px; }
label { display: flex; flex-direction: column; gap: 5px; font-size: 12px; }
p { color: #94a3b8; font-size: 12px; line-height: 1.5; margin: 0; }
</style>
