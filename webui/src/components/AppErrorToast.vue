<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import DialogCloseButton from './DialogCloseButton.vue'

const AUTO_DISMISS_DELAY_MS = 5_000

const props = defineProps<{
  message: string | null
  placement: 'desktop' | 'mobile'
}>()

const emit = defineEmits<{
  dismiss: []
}>()

let dismissTimer: number | null = null

function clearDismissTimer() {
  if (dismissTimer === null) return
  window.clearTimeout(dismissTimer)
  dismissTimer = null
}

function dismiss() {
  clearDismissTimer()
  emit('dismiss')
}

watch(
  () => props.message,
  (message) => {
    clearDismissTimer()
    if (!String(message || '').trim()) return
    dismissTimer = window.setTimeout(dismiss, AUTO_DISMISS_DELAY_MS)
  },
  { immediate: true },
)

onBeforeUnmount(clearDismissTimer)
</script>

<template>
  <Transition name="app-error-toast">
    <aside
      v-if="message"
      :class="['app-error-toast', `is-${placement}`]"
      role="alert"
      aria-live="assertive"
      aria-atomic="true"
    >
      <span class="app-error-toast-icon" aria-hidden="true">!</span>
      <span class="app-error-toast-message">{{ message }}</span>
      <DialogCloseButton class="app-error-toast-close" aria-label="关闭错误提示" @click="dismiss" />
    </aside>
  </Transition>
</template>

<style scoped>
.app-error-toast {
  z-index: 200;
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) 30px;
  align-items: start;
  gap: 10px;
  box-sizing: border-box;
  padding: 12px 12px 12px 14px;
  border: 1px solid rgba(248, 113, 113, 0.48);
  border-radius: 10px;
  background: rgba(69, 10, 10, 0.94);
  color: rgba(254, 226, 226, 0.98);
  box-shadow: 0 16px 38px rgba(2, 6, 23, 0.38);
  backdrop-filter: blur(10px);
}

.app-error-toast.is-desktop {
  position: absolute;
  right: 16px;
  bottom: 16px;
  left: 16px;
}

.app-error-toast.is-mobile {
  position: absolute;
  top: 12px;
  right: 12px;
  left: 12px;
}

.app-error-toast-icon {
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
  border-radius: 50%;
  background: rgba(248, 113, 113, 0.2);
  color: #fecaca;
  font-size: 13px;
  font-weight: 800;
  line-height: 1;
}

.app-error-toast-message {
  min-width: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.5;
}

.app-error-toast-close {
  margin: -3px -3px 0 0;
}

.app-error-toast-enter-active,
.app-error-toast-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.app-error-toast-enter-from,
.app-error-toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (prefers-reduced-motion: reduce) {
  .app-error-toast-enter-active,
  .app-error-toast-leave-active {
    transition: none;
  }
}
</style>
