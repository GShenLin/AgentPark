<script setup lang="ts">
import { ref } from 'vue'
import ActionButton from './ActionButton.vue'
import FormTextInput from './FormTextInput.vue'
import { t } from '../i18n'

const props = defineProps<{
  busy?: boolean
  error?: string
}>()

const emit = defineEmits<{
  submit: [username: string]
}>()

const username = ref('')

function submit() {
  const value = username.value.trim()
  if (!value || props.busy) return
  emit('submit', value)
}
</script>

<template>
  <div class="access-overlay">
    <form class="access-dialog" @submit.prevent="submit">
      <h1>{{ t('accessDialog.title') }}</h1>
      <p>{{ t('accessDialog.description') }}</p>
      <label>
        <span>{{ t('access.username') }}</span>
        <FormTextInput v-model="username" maxlength="80" autocomplete="name" autofocus />
      </label>
      <div v-if="error" class="access-error">{{ error }}</div>
      <ActionButton variant="primary" type="submit" :disabled="busy || !username.trim()">
        {{ busy ? t('accessDialog.registering') : t('accessDialog.enter') }}
      </ActionButton>
    </form>
  </div>
</template>

<style scoped>
.access-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--ui-dialog-backdrop);
}
.access-dialog {
  width: min(440px, 100%);
  display: grid;
  gap: 18px;
  padding: 28px;
  border: 1px solid var(--ui-dialog-border);
  border-radius: var(--ui-dialog-radius);
  background: var(--ui-dialog-background);
  color: var(--ui-dialog-text);
  box-shadow: var(--ui-dialog-shadow);
}
h1, p { margin: 0; }
p { color: #aebbd0; line-height: 1.55; }
label { display: grid; gap: 8px; }
.access-error { color: #fca5a5; }
</style>
