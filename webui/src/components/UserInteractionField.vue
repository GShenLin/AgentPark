<script setup lang="ts">
import type { UserInteractionField } from '../apiTypes'
import FormCheckbox from './FormCheckbox.vue'
import FormSelect from './FormSelect.vue'
import FormTextInput from './FormTextInput.vue'
import ExpandableTextarea from './ExpandableTextarea.vue'

const props = defineProps<{ field: UserInteractionField; value: unknown; error?: string; files: string[] }>()
const emit = defineEmits<{ value: [value: unknown]; files: [files: File[]] }>()
function toggle(value: string) {
  const current = Array.isArray(props.value) ? props.value as string[] : []
  emit('value', current.includes(value) ? current.filter(item => item !== value) : [...current, value])
}
function selected(value: string) { return Array.isArray(props.value) && props.value.includes(value) }
</script>

<template>
  <div class="interaction-field" :class="{ 'has-error': error }" role="group" :aria-labelledby="`label-${field.id}`">
    <label :id="`label-${field.id}`" :for="`input-${field.id}`" class="interaction-label">
      {{ field.label }} <span class="interaction-required">{{ field.required ? '必填' : '选填' }}</span>
    </label>
    <small v-if="field.description" :id="`help-${field.id}`">{{ field.description }}</small>
    <FormTextInput v-if="field.type === 'text'" :id="`input-${field.id}`" :model-value="String(value ?? '')"
      :placeholder="field.placeholder" :aria-invalid="!!error" @update:model-value="emit('value', $event)" />
    <ExpandableTextarea v-else-if="field.type === 'textarea'" :id="`input-${field.id}`" :model-value="String(value ?? '')"
      :placeholder="field.placeholder" :aria-label="field.label" :aria-invalid="!!error" @update:model-value="emit('value', $event)" />
    <FormSelect v-else-if="field.type === 'select'" :id="`input-${field.id}`" :model-value="String(value ?? '')"
      :aria-invalid="!!error" @change="emit('value', $event)">
      <option value="">请选择</option>
      <option v-for="option in field.options" :key="option.value" :value="option.value" :disabled="option.disabled">{{ option.label }}</option>
    </FormSelect>
    <div v-else-if="field.type === 'multiselect'" class="interaction-options">
      <button v-for="option in field.options" :key="option.value" type="button" :disabled="option.disabled"
        :aria-pressed="selected(option.value)" :class="{ selected: selected(option.value) }" @click="toggle(option.value)">{{ option.label }}</button>
    </div>
    <FormCheckbox v-else-if="field.type === 'checkbox'" :id="`input-${field.id}`" :model-value="value === true"
      :aria-label="field.label" @update:model-value="emit('value', $event)" />
    <template v-else-if="field.type === 'file'">
      <input :id="`input-${field.id}`" type="file" :accept="field.accept" :multiple="field.multiple"
        @change="emit('files', Array.from(($event.target as HTMLInputElement).files || []))" />
      <small v-if="files.length">{{ files.join('、') }}</small>
      <small>尚未上传的文件在刷新窗口后需要重新选择。</small>
    </template>
    <small v-if="error" class="interaction-field-error" role="alert">{{ error }}</small>
  </div>
</template>
