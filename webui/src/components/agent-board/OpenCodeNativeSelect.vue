<script setup lang="ts">
import { computed } from 'vue'
import type { OpenCodeField } from '../../harnessApi'
import type { OpenCodeCatalog } from '../../composables/useOpenCodeOptions'
import FormSelect from '../FormSelect.vue'
import ActionButton from '../ActionButton.vue'

const props = defineProps<{ fieldKey: OpenCodeField; value: string; catalog: OpenCodeCatalog }>()
const emit = defineEmits<{ change: [value: string]; refresh: [] }>()
const options = computed(() => props.catalog.options[props.fieldKey])
const missing = computed(() => !options.value.some(item => item.value === props.value))
</script>

<template>
  <div class="native-select">
    <FormSelect :model-value="value" :disabled="catalog.loading || !options.length" @change="emit('change', $event)">
      <option v-if="missing" :value="value" disabled>
        {{ value || '模型默认' }}{{ catalog.loading ? '（加载中…）' : '（当前不可用）' }}
      </option>
      <option v-for="item in options" :key="item.value" :value="item.value">{{ item.label }}</option>
    </FormSelect>
    <template v-if="fieldKey === 'native_model'">
      <p v-if="catalog.error" class="catalog-error" role="alert">{{ catalog.error }}</p>
      <ActionButton compact :disabled="catalog.loading" @click.prevent="emit('refresh')">
        {{ catalog.loading ? '正在读取选项…' : '刷新可用选项' }}
      </ActionButton>
    </template>
  </div>
</template>

<style scoped>
.native-select { display: grid; gap: 6px; min-width: 0; }
.native-select button { justify-self: start; }
.catalog-error { margin: 0; color: var(--error-color, #dc6565); overflow-wrap: anywhere; font-size: 12px; }
</style>
