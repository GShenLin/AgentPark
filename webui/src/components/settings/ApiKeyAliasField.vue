<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { addApiKeyAlias, getApiKeyAliases } from '../../settingsApi'
import ActionButton from '../ActionButton.vue'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'

const props = defineProps<{
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const names = ref<string[]>([])
const loading = ref(false)
const saving = ref(false)
const adding = ref(false)
const name = ref('')
const apiKey = ref('')
const error = ref('')

const options = computed(() => {
  const current = props.modelValue.trim()
  return current && !names.value.includes(current)
    ? [current, ...names.value]
    : names.value
})

async function loadAliases() {
  loading.value = true
  error.value = ''
  try {
    const result = await getApiKeyAliases()
    names.value = Array.isArray(result.names) ? result.names : []
  } catch (cause) {
    error.value = String((cause as Error)?.message || cause)
  } finally {
    loading.value = false
  }
}

function openAddForm() {
  adding.value = true
  error.value = ''
}

function closeAddForm() {
  if (saving.value) return
  adding.value = false
  name.value = ''
  apiKey.value = ''
  error.value = ''
}

async function saveAlias() {
  const safeName = name.value.trim()
  if (!safeName || !apiKey.value.trim()) {
    error.value = 'Name 和密钥不能为空。'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const result = await addApiKeyAlias({ name: safeName, apiKey: apiKey.value })
    names.value = Array.isArray(result.names) ? result.names : []
    emit('update:modelValue', result.selected || safeName)
    adding.value = false
    name.value = ''
    apiKey.value = ''
  } catch (cause) {
    error.value = String((cause as Error)?.message || cause)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void loadAliases()
})
</script>

<template>
  <div class="api-key-alias-field">
    <span>API Key Name</span>
    <div class="api-key-alias-picker">
      <FormSelect
        class="api-key-alias-select"
        :model-value="modelValue"
        :disabled="loading"
        @change="emit('update:modelValue', $event)"
      >
        <option value="">{{ loading ? 'Loading…' : (options.length ? 'Unset' : 'No API keys') }}</option>
        <option v-for="option in options" :key="option" :value="option">
          {{ option }}{{ option === modelValue && !names.includes(option) ? ' (missing)' : '' }}
        </option>
      </FormSelect>
      <ActionButton :disabled="loading || saving" @click="openAddForm">Add</ActionButton>
    </div>

    <div v-if="adding" class="api-key-alias-add-form">
      <FormTextInput
        v-model="name"
        placeholder="Name"
        autocomplete="off"
        spellcheck="false"
        @keydown.enter.prevent="saveAlias"
      />
      <FormTextInput
        v-model="apiKey"
        type="password"
        placeholder="API Key"
        autocomplete="new-password"
        @keydown.enter.prevent="saveAlias"
      />
      <div class="api-key-alias-actions">
        <ActionButton variant="primary" :disabled="saving" @click="saveAlias">
          {{ saving ? 'Saving…' : 'Save' }}
        </ActionButton>
        <ActionButton :disabled="saving" @click="closeAddForm">Cancel</ActionButton>
      </div>
    </div>

    <small v-if="error" class="api-key-alias-error">{{ error }}</small>
    <small v-else>References a key name stored in .auth/api-keys/aliases.json.</small>
  </div>
</template>

<style scoped>
.api-key-alias-field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
  color: rgba(226, 232, 240, 0.94);
  font-size: 12px;
}

.api-key-alias-picker {
  display: flex;
  min-width: 0;
  gap: 6px;
}

.api-key-alias-select {
  min-width: 0;
  flex: 1;
}

.api-key-alias-add-form {
  display: grid;
  grid-template-columns: minmax(120px, 0.8fr) minmax(180px, 1.4fr);
  gap: 6px;
  padding: 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.5);
}

.api-key-alias-actions {
  display: flex;
  grid-column: 1 / -1;
  justify-content: flex-end;
  gap: 6px;
}

small {
  color: rgba(148, 163, 184, 0.92);
}

.api-key-alias-error {
  color: rgba(254, 202, 202, 0.96);
  overflow-wrap: anywhere;
}

@media (max-width: 900px) {
  .api-key-alias-add-form {
    grid-template-columns: 1fr;
  }
}
</style>
