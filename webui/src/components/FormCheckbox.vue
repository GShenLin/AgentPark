<script setup lang="ts">
defineOptions({ inheritAttrs: false })

withDefaults(defineProps<{
  modelValue: boolean
  disabled?: boolean
}>(), {
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <input
    v-bind="$attrs"
    class="form-checkbox"
    type="checkbox"
    :checked="modelValue"
    :disabled="disabled"
    @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
  />
</template>

<style scoped>
.form-checkbox {
  flex: 0 0 auto;
  width: 16px;
  height: 16px;
  margin: 0;
  accent-color: var(--form-control-focus, var(--ui-control-focus, #38bdf8));
}
</style>
