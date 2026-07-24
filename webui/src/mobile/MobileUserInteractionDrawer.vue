<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import UserInteractionForm from '../components/UserInteractionForm.vue'
import { useUserInteractions } from '../composables/useUserInteractions'

const interactions = useUserInteractions()
const error = ref('')
const activeRequest = interactions.activeRequest
const submitting = computed(() => interactions.submittingRequestId.value === activeRequest.value?.id)

async function submitActive(response: Record<string, unknown>) {
  const request = activeRequest.value
  if (!request) return
  error.value = ''
  try {
    await interactions.submitResponse(request.id, response)
  } catch (submitError) {
    error.value = submitError instanceof Error ? submitError.message : String(submitError)
  }
}

watch(() => activeRequest.value?.id, () => { error.value = '' })
</script>

<template>
  <div v-if="activeRequest" class="mobile-interaction-backdrop">
    <section class="mobile-interaction-drawer" role="dialog" aria-modal="true">
      <div class="mobile-interaction-grabber"></div>
      <header class="mobile-interaction-header">
        <div>
          <div class="interaction-kicker">Agent 请求确认</div>
          <h2>{{ activeRequest.schema.title }}</h2>
        </div>
        <div class="mobile-interaction-count">{{ interactions.activeIndex.value + 1 }} / {{ interactions.requests.value.length }}</div>
      </header>
      <div v-if="interactions.requests.value.length > 1" class="mobile-interaction-navigation">
        <button type="button" @click="interactions.showPrevious">上一项</button>
        <span>共 {{ interactions.requests.value.length }} 个待确认请求</span>
        <button type="button" @click="interactions.showNext">下一项</button>
      </div>
      <div class="mobile-interaction-content">
        <UserInteractionForm :request="activeRequest" :submitting="submitting" :error="error" @submit="submitActive" @error="error = $event" />
      </div>
    </section>
  </div>
</template>

<style scoped>
.mobile-interaction-backdrop {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: flex;
  align-items: flex-end;
  background: rgba(2, 6, 23, 0.58);
  backdrop-filter: blur(3px);
}

.mobile-interaction-drawer {
  width: 100%;
  max-height: min(86vh, 820px);
  display: flex;
  flex-direction: column;
  padding: 8px 16px max(16px, env(safe-area-inset-bottom));
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-bottom: 0;
  border-radius: 20px 20px 0 0;
  background: rgba(15, 23, 42, 0.99);
  box-shadow: 0 -20px 50px rgba(2, 6, 23, 0.55);
  animation: mobileInteractionIn 0.22s ease-out;
}

.mobile-interaction-grabber {
  width: 42px;
  height: 4px;
  margin: 0 auto 10px;
  border-radius: 99px;
  background: rgba(148, 163, 184, 0.55);
}

.mobile-interaction-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.mobile-interaction-header h2 {
  margin: 4px 0 0;
  font-size: 18px;
}

.mobile-interaction-count {
  flex: 0 0 auto;
  color: #94a3b8;
  font-size: 12px;
}

.mobile-interaction-navigation {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

.mobile-interaction-navigation span {
  color: #94a3b8;
  text-align: center;
  font-size: 12px;
}

.mobile-interaction-navigation button {
  padding: 7px 11px;
  font-size: 12px;
}

.mobile-interaction-content {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.mobile-interaction-content :deep(.interaction-agent) {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
}

.mobile-interaction-content :deep(.interaction-fields) {
  margin-top: 16px;
}

.mobile-interaction-content :deep(.interaction-actions) {
  position: sticky;
  bottom: 0;
  padding-top: 12px;
  background: linear-gradient(transparent, rgba(15, 23, 42, 0.99) 24%);
}

.mobile-interaction-content :deep(.interaction-actions button) {
  width: 100%;
  min-height: 44px;
}

@keyframes mobileInteractionIn {
  from { transform: translateY(100%); }
  to { transform: translateY(0); }
}
</style>
