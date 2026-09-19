<script setup lang="ts">
import { computed } from 'vue'
import type { ProviderInfo } from '../../api'
import type { ConversationContextSettings } from '../../conversationContextSettings'
import { t } from '../../i18n'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'

const props = defineProps<{ data: Record<string, unknown>; defaults?: ConversationContextSettings; providers: ProviderInfo[] }>()
const emit = defineEmits<{ 'update:data': [value: Record<string, unknown>] }>()
const effective = computed(() => props.defaults ? { ...props.defaults, ...props.data } : null)
const providers = computed(() => props.providers.filter(p => p.supportmode.includes('chat') || p.supportmode.includes('imagechat')).map(p => p.id))
const fields = ['input_tokens', 'retain_tokens', 'summary_tokens'] as const
function setNumber(key: keyof ConversationContextSettings, value: string) {
  const next = { ...props.data }
  if (value.trim()) next[key] = Number(value)
  else delete next[key]
  emit('update:data', next)
}
</script>

<template>
  <section class="settings-group conversation-settings">
    <h2>{{ t('conversation.title') }}</h2>
    <p>{{ t('conversation.description') }}</p>
    <p class="help">{{ t('conversation.effect') }}</p>
    <p v-if="!effective" role="alert">{{ t('longMemory.unavailable') }}</p>
    <div v-else class="conversation-grid">
      <label v-for="key in fields" :key="key">
        <span>{{ t(`conversation.${key}`) }}</span>
        <FormTextInput :model-value="String(effective[key])" type="number" :min="key === 'input_tokens' ? 4096 : 1" step="1" @update:model-value="setNumber(key, $event)" />
        <small>{{ t(`conversation.${key}Help`) }}</small>
      </label>
      <label>
        <span>{{ t('conversation.provider') }}</span>
        <FormSelect :model-value="String(effective.provider)" @update:model-value="emit('update:data', { ...data, provider: $event })">
          <option value="">{{ t('conversation.providerDefault') }}</option>
          <option v-if="effective.provider && !providers.includes(String(effective.provider))" :value="String(effective.provider)">{{ effective.provider }} — {{ t('longMemory.providerUnavailable') }}</option>
          <option v-for="id in providers" :key="id" :value="id">{{ id }}</option>
        </FormSelect>
        <small>{{ t('conversation.providerHelp') }}</small>
      </label>
    </div>
  </section>
</template>

<style scoped>
.conversation-settings { border: 1px solid var(--border-subtle); border-radius: 8px; padding: 16px; }
h2 { margin: 0 0 10px; font-size: 16px; }
p { margin: 6px 0; line-height: 1.5; }
.help, small { color: var(--text-secondary); }
.conversation-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 16px; }
label { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
small { line-height: 1.5; }
@media (max-width: 800px) { .conversation-grid { grid-template-columns: 1fr; } }
</style>
