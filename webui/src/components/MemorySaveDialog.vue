<script setup lang="ts">
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

function updateFilename(event: Event) {
  emit('update:filename', String((event.target as HTMLInputElement | null)?.value || ''))
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="save-dialog-backdrop" @mousedown.self="emit('cancel')">
      <form class="save-dialog" @submit.prevent="emit('confirm')">
        <div class="save-dialog-head">
          <div class="save-dialog-title">保存 Markdown</div>
          <button class="save-dialog-close" type="button" aria-label="取消" @click="emit('cancel')">x</button>
        </div>
        <div v-if="targetDir" class="save-dialog-target" :title="targetDir">{{ targetDir }}</div>
        <input
          class="save-dialog-input"
          type="text"
          :value="filename"
          :disabled="saving"
          autofocus
          placeholder="文件名"
          @input="updateFilename"
        />
        <div v-if="error" class="save-dialog-error">{{ error }}</div>
        <div class="save-dialog-actions">
          <button class="save-dialog-btn" type="button" :disabled="saving" @click="emit('cancel')">取消</button>
          <button class="save-dialog-btn primary" type="submit" :disabled="saving">确认</button>
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
  background: rgba(2, 6, 23, 0.72);
}

.save-dialog {
  width: min(420px, 100%);
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 10px;
  background: #0f172a;
  color: rgba(226, 232, 240, 0.96);
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.36);
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

.save-dialog-close {
  width: 26px;
  height: 26px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 7px;
  background: rgba(15, 23, 42, 0.7);
  color: rgba(203, 213, 225, 0.9);
  cursor: pointer;
}

.save-dialog-target {
  color: rgba(148, 163, 184, 0.92);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.save-dialog-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid rgba(148, 163, 184, 0.3);
  background: rgba(2, 6, 23, 0.72);
  color: rgba(248, 250, 252, 0.96);
  border-radius: 8px;
  font-size: 13px;
  padding: 9px 10px;
  outline: none;
}

.save-dialog-input:focus {
  border-color: rgba(56, 189, 248, 0.72);
}

.save-dialog-error {
  color: rgba(252, 165, 165, 0.96);
  font-size: 12px;
  line-height: 1.4;
}

.save-dialog-actions {
  justify-content: flex-end;
}

.save-dialog-btn {
  border: 1px solid rgba(148, 163, 184, 0.3);
  background: rgba(15, 23, 42, 0.78);
  color: rgba(226, 232, 240, 0.94);
  border-radius: 8px;
  font-size: 12px;
  padding: 6px 12px;
  cursor: pointer;
}

.save-dialog-btn.primary {
  border-color: rgba(56, 189, 248, 0.7);
  background: rgba(14, 116, 144, 0.42);
}

.save-dialog-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
