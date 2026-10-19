<script setup lang="ts">
import { ref } from 'vue'
import ActionButton from '../ActionButton.vue'
import { listNativeHarnessModels } from '../../harnessApi'
import { t } from '../../i18n'

const props = defineProps<{ harnessId: 'opencode' | 'antigravity'; disabled: boolean }>()
const models = ref<string[]>([])
const loading = ref(false)
const error = ref('')
async function refresh() {
  loading.value = true
  error.value = ''
  try {
    models.value = (await listNativeHarnessModels(props.harnessId)).models
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="native-models">
    <p>{{ t(`harness.${harnessId}.run`) }}</p>
    <p>{{ t(`harness.${harnessId}.models`) }}</p>
    <ActionButton compact :disabled="disabled || loading" @click="refresh">
      {{ t(loading ? 'harness.native.loading' : 'harness.native.refresh') }}
    </ActionButton>
    <p v-if="error" role="alert" class="catalog-error">{{ error }}</p>
    <div v-if="models.length" class="model-catalog">
      <p>{{ t('harness.native.select') }}</p>
      <ul><li v-for="model in models" :key="model"><code>{{ model }}</code></li></ul>
    </div>
  </div>
</template>

<style scoped>
.native-models { margin-top: 16px; font-size: 13px; line-height: 1.6; }
.native-models p { margin: 8px 0; }
.model-catalog { max-height: 240px; overflow: auto; }
.model-catalog ul { padding-left: 20px; }
.model-catalog code { overflow-wrap: anywhere; user-select: text; }
.catalog-error { color: #dc6565; overflow-wrap: anywhere; }
</style>
