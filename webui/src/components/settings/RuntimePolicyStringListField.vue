<script setup lang="ts">
import { ref } from 'vue'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import FormTextInput from '../FormTextInput.vue'

const props = defineProps<{
  label: string
  values: string[]
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:values': [values: string[]]
}>()

const newValue = ref('')

function updateValue(index: number, value: string) {
  const next = [...props.values]
  next[index] = value
  emit('update:values', next)
}

function removeValue(index: number) {
  emit('update:values', props.values.filter((_value, itemIndex) => itemIndex !== index))
}

function addValue() {
  const value = newValue.value.trim()
  if (!value || props.values.includes(value)) return
  emit('update:values', [...props.values, value])
  newValue.value = ''
}
</script>

<template>
  <div class="runtime-policy-list-field">
    <span class="runtime-policy-list-label">{{ label }}</span>
    <div v-for="(value, index) in values" :key="`${index}:${value}`" class="runtime-policy-list-row">
      <FormTextInput
        :model-value="value"
        :disabled="disabled"
        @change="updateValue(index, $event)"
      />
      <DangerButton icon :disabled="disabled" aria-label="Remove item" @click="removeValue(index)">×</DangerButton>
    </div>
    <div class="runtime-policy-list-add">
      <FormTextInput
        v-model="newValue"
        :disabled="disabled"
        placeholder="Add item"
        @keydown.enter.prevent="addValue"
      />
      <ActionButton compact :disabled="disabled || !newValue.trim()" @click="addValue">Add</ActionButton>
    </div>
  </div>
</template>

<style scoped>
.runtime-policy-list-field {
  display: grid;
  gap: 7px;
}

.runtime-policy-list-label {
  font-size: 12px;
  font-weight: 650;
}

.runtime-policy-list-row,
.runtime-policy-list-add {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 7px;
}

</style>
