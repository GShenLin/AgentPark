<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { listAgentProfiles, type AgentProfile } from '../../api'
import { t } from '../../i18n'
import FormSelect from '../FormSelect.vue'

defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const profiles = ref<AgentProfile[]>([])
const loading = ref(false)
const error = ref('')
const choices = computed(() => profiles.value.filter(profile => profile.node_type_id === 'agent_node'))

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    profiles.value = await listAgentProfiles()
  } catch (cause) {
    error.value = String(cause instanceof Error ? cause.message : cause)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void refresh()
  window.addEventListener('agent-profiles-changed', refresh)
})
onBeforeUnmount(() => window.removeEventListener('agent-profiles-changed', refresh))
</script>

<template>
  <FormSelect :model-value="modelValue" :disabled="loading || !!error"
    @update:model-value="emit('update:modelValue', $event)">
    <option v-if="!choices.some(profile => profile.id === modelValue)" :value="modelValue" disabled>
      {{ modelValue || t('longMemory.selectProfile') }} — {{ loading ? t('common.loading') : t('longMemory.profileUnavailable') }}
    </option>
    <option v-for="profile in choices" :key="profile.id" :value="profile.id">
      {{ profile.name === profile.id ? profile.id : `${profile.name} (${profile.id})` }}
    </option>
  </FormSelect>
  <small v-if="error" role="alert">{{ error }} <button type="button" @click="refresh">{{ t('common.refresh') }}</button></small>
</template>
