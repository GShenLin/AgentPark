<script setup lang="ts">
import { selectFolder } from '../../api'

const props = withDefaults(defineProps<{
  value?: string
  inputAttrs?: Record<string, string | number>
}>(), {
  value: '',
  inputAttrs: () => ({}),
})

const emit = defineEmits<{
  'update-value': [value: string]
  error: [message: string]
}>()

async function chooseWorkingPath() {
  try {
    const res = await selectFolder(String(props.value ?? ''))
    const selectedPath = String(res?.path || '').trim()
    if (selectedPath) {
      emit('update-value', selectedPath)
    }
  } catch (e: any) {
    emit('error', String(e?.message || e))
  }
}
</script>

<template>
  <div class="path-picker">
    <input
      class="field-input"
      type="text"
      v-bind="inputAttrs"
      :value="String(value ?? '')"
      @input="emit('update-value', ($event.target as HTMLInputElement).value)"
    />
    <button class="path-picker-btn" type="button" title="选择工作路径" @click="chooseWorkingPath">...</button>
  </div>
</template>

<style scoped>
.path-picker {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 34px;
  gap: 6px;
  align-items: center;
}

.field-input {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.88);
  color: #f8fafc;
  padding: 10px 12px;
  outline: none;
}

.field-input:focus {
  border-color: rgba(56, 189, 248, 0.7);
}

.path-picker-btn {
  height: 36px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.88);
  color: #f8fafc;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}

.path-picker-btn:hover {
  border-color: rgba(56, 189, 248, 0.7);
}
</style>
