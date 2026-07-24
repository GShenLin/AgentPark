<script setup lang="ts">
import { computed } from 'vue'
import { useWorkAlerts } from '../composables/useWorkAlerts'

const {
  alerts,
  latestAlert,
  audioReady,
  notificationPermission,
  dismissWorkAlert,
  activateWorkAlert,
  enableWorkAlertAudio,
  enableDesktopNotifications,
} = useWorkAlerts()

const isMobile = computed(() => window.matchMedia('(max-width: 760px)').matches)
const pendingCount = computed(() => Math.max(0, alerts.value.length - 1))
const isNavigable = computed(() => latestAlert.value?.kind === 'work_persisted')

function openLatestAlert() {
  if (latestAlert.value) activateWorkAlert(latestAlert.value)
}

function onToastKeyDown(event: KeyboardEvent) {
  if (!isNavigable.value || (event.key !== 'Enter' && event.key !== ' ')) return
  event.preventDefault()
  openLatestAlert()
}

async function enableAlerts() {
  await enableWorkAlertAudio()
  if (!isMobile.value && notificationPermission.value === 'default') {
    await enableDesktopNotifications()
  }
}
</script>

<template>
  <Transition name="work-alert">
    <aside v-if="latestAlert" class="work-alert-toast" :class="{ navigable: isNavigable }" role="status" aria-live="polite">
      <button class="work-alert-close" type="button" aria-label="关闭提醒" @click.stop="dismissWorkAlert(latestAlert.id)">×</button>
      <div
        class="work-alert-content"
        :class="{ navigable: isNavigable }"
        :role="isNavigable ? 'button' : undefined"
        :tabindex="isNavigable ? 0 : undefined"
        :aria-label="isNavigable ? `打开 ${latestAlert.graphId} 中的 ${latestAlert.nodeName}` : undefined"
        @click="openLatestAlert"
        @keydown="onToastKeyDown"
      >
        <div class="work-alert-kicker">{{ latestAlert.graphId }} · {{ latestAlert.nodeName }}</div>
        <div class="work-alert-title">{{ latestAlert.title }}</div>
        <div v-if="latestAlert.message" class="work-alert-message">{{ latestAlert.message }}</div>
      </div>
      <div class="work-alert-actions">
        <span v-if="pendingCount" class="work-alert-count">另有 {{ pendingCount }} 条提醒</span>
        <button v-if="!audioReady || (!isMobile && notificationPermission === 'default')" type="button" @click.stop="enableAlerts">
          启用提醒
        </button>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.work-alert-toast {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 4000;
  width: min(380px, calc(100vw - 28px));
  padding: 15px 42px 14px 16px;
  border: 1px solid rgba(96, 165, 250, 0.38);
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.96);
  color: #f8fafc;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(18px);
}

.work-alert-content.navigable {
  cursor: pointer;
}

.work-alert-toast.navigable:hover,
.work-alert-toast.navigable:focus-within {
  border-color: rgba(96, 165, 250, 0.75);
  box-shadow: 0 20px 56px rgba(0, 0, 0, 0.5), 0 0 0 2px rgba(96, 165, 250, 0.18);
}

.work-alert-content.navigable:focus-visible {
  outline: none;
}

.work-alert-close {
  position: absolute;
  top: 7px;
  right: 8px;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #94a3b8;
  font-size: 22px;
}

.work-alert-kicker {
  color: #60a5fa;
  font-size: 12px;
  font-weight: 700;
}

.work-alert-title {
  margin-top: 2px;
  font-size: 15px;
  font-weight: 700;
}

.work-alert-message {
  display: -webkit-box;
  margin-top: 6px;
  overflow: hidden;
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.work-alert-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
}

.work-alert-actions button {
  margin-left: auto;
  padding: 5px 10px;
  font-size: 12px;
}

.work-alert-count {
  color: #94a3b8;
  font-size: 12px;
}

.work-alert-enter-active,
.work-alert-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
}

.work-alert-enter-from,
.work-alert-leave-to {
  opacity: 0;
  transform: translateY(14px);
}

@media (max-width: 760px) {
  .work-alert-toast {
    right: 10px;
    bottom: max(10px, env(safe-area-inset-bottom));
    left: 10px;
    width: auto;
  }
}
</style>
