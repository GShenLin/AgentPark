<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { listNativeHarnessModels } from '../../harnessApi'
import FormSelect from '../FormSelect.vue'
import ActionButton from '../ActionButton.vue'

const props = defineProps<{ harnessId: 'antigravity'; value: string }>()
const emit = defineEmits<{ change: [value: string] }>()
const models = ref<string[]>([])
const loading = ref(false)
const error = ref('')
const missing = computed(() => !models.value.includes(props.value))
let requestId = 0

async function refresh() {
  const current = ++requestId
  loading.value = true
  error.value = ''
  try {
    const result = await listNativeHarnessModels(props.harnessId)
    if (current !== requestId) return
    models.value = result.models
    if (!models.value.length) error.value = '当前账号的模型目录为空。'
  } catch (cause) {
    if (current !== requestId) return
    models.value = []
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (current === requestId) loading.value = false
  }
}

watch(() => props.harnessId, () => {
  models.value = []
  void refresh()
}, { immediate: true })
onScopeDispose(() => { ++requestId })
</script>

<template>
  <div class="native-model-select">
    <FormSelect :model-value="value" :disabled="loading || !models.length" @change="emit('change', $event)">
      <option v-if="missing" :value="value" disabled>
        {{ value || '请选择模型' }}{{ loading ? '（加载中…）' : '（当前不可用）' }}
      </option>
      <option v-for="model in models" :key="model" :value="model">{{ model }}</option>
    </FormSelect>
    <p v-if="error" class="catalog-error" role="alert">{{ error }}</p>
    <ActionButton compact :disabled="loading" @click.prevent="refresh">
      {{ loading ? '正在读取模型…' : '刷新可用模型' }}
    </ActionButton>
  </div>
</template>

<style scoped>
.native-model-select { display: grid; gap: 6px; min-width: 0; }
.native-model-select button { justify-self: start; }
.catalog-error { margin: 0; color: var(--error-color, #dc6565); overflow-wrap: anywhere; font-size: 12px; }
</style>
