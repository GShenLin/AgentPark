<script setup lang="ts">
import ActionButton from './ActionButton.vue'
import DialogCloseButton from './DialogCloseButton.vue'
import FormTextInput from './FormTextInput.vue'
import { t } from '../i18n'

defineProps<{
  open: boolean
  filename: string
  targetDir: string
  error: string | null
  saving: boolean
}>()

const emit = defineEmits<{
  (event: 'update:filename', value: string): void
  (event: 'confirm'): void
  (event: 'cancel'): void
}>()

</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="save-dialog-backdrop" @mousedown.self="emit('cancel')">
      <form class="save-dialog" @submit.prevent="emit('confirm')">
        <div class="save-dialog-head">
          <div class="save-dialog-title">{{ t('memory.saveMarkdown') }}</div>
          <DialogCloseButton :aria-label="t('common.cancel')" @click="emit('cancel')" />
        </div>
        <div v-if="targetDir" class="save-dialog-target" :title="targetDir">{{ targetDir }}</div>
        <FormTextInput
          class="save-dialog-input"
          :model-value="filename"
          :disabled="saving"
          autofocus
          :placeholder="t('memory.filename')"
          @update:model-value="emit('update:filename', $event)"
        />
        <div v-if="error" class="save-dialog-error">{{ error }}</div>
        <div class="save-dialog-actions">
          <ActionButton compact :disabled="saving" @click="emit('cancel')">{{ t('common.cancel') }}</ActionButton>
          <ActionButton variant="primary" compact type="submit" :disabled="saving">{{ t('memory.confirm') }}</ActionButton>
        </div>
      </form>
    </div>
  </Teleport>
</template>

<style scoped>
.save-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--ui-dialog-backdrop);
}

.save-dialog {
  width: min(420px, 100%);
  border: 1px solid var(--ui-dialog-border);
  border-radius: var(--ui-dialog-radius);
  background: var(--ui-dialog-background);
  color: var(--ui-dialog-text);
  box-shadow: var(--ui-dialog-shadow);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.save-dialog-head,
.save-dialog-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.save-dialog-title {
  font-size: 14px;
  font-weight: 700;
}

.save-dialog-target {
  color: rgba(148, 163, 184, 0.92);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.save-dialog-error {
  color: rgba(252, 165, 165, 0.96);
  font-size: 12px;
  line-height: 1.4;
}

.save-dialog-actions {
  justify-content: flex-end;
}

</style>
