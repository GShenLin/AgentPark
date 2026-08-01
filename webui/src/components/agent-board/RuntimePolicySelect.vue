<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  getRuntimePolicySettings,
  type RuntimePolicySettingsDocument,
} from '../../settingsApi'
import FormSelect from '../FormSelect.vue'

const props = defineProps<{
  value: unknown
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update-value': [value: Record<string, unknown> | null]
  error: [message: string]
}>()

const catalog = ref<RuntimePolicySettingsDocument | null>(null)
const loading = ref(false)

function selectionObject(): Record<string, unknown> {
  if (props.value == null || props.value === '') return {}
  const parsed = typeof props.value === 'string' ? JSON.parse(props.value) : props.value
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Runtime policy must be a JSON object.')
  }
  return { ...(parsed as Record<string, unknown>) }
}

const selectedPolicyId = computed(() => {
  try {
    return String(selectionObject().policy_id || '')
  } catch {
    return ''
  }
})

function selectPolicy(policyId: string) {
  emit('error', '')
  try {
    const next = selectionObject()
    if (policyId) {
      next.policy_id = policyId
    } else {
      delete next.policy_id
    }
    emit('update-value', Object.keys(next).length ? next : null)
  } catch (error) {
    emit('error', String((error as { message?: unknown })?.message || error || '').trim())
  }
}

onMounted(async () => {
  loading.value = true
  try {
    catalog.value = await getRuntimePolicySettings()
  } catch (error) {
    emit('error', String((error as { message?: unknown })?.message || error || '').trim())
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <label class="runtime-policy-select">
    <span>Runtime Policy</span>
    <FormSelect
      :model-value="selectedPolicyId"
      :disabled="disabled || loading || !catalog"
      @change="selectPolicy"
    >
      <option value="">
        Workspace default{{ catalog?.default_policy_id ? ` (${catalog.default_policy_id})` : '' }}
      </option>
      <option
        v-for="policy in catalog?.policies || []"
        :key="policy.policy_id"
        :value="policy.policy_id"
      >
        {{ policy.policy_id }}
      </option>
    </FormSelect>
  </label>
</template>

<style scoped>
.runtime-policy-select {
  display: grid;
  gap: 6px;
}

.runtime-policy-select > span {
  font-size: 12px;
  font-weight: 650;
}

</style>
