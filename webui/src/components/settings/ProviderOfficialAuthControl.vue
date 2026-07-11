<script setup lang="ts">
import type { CodexAuthStatus } from '../../settingsApi'

defineProps<{
  enabled: boolean
  label?: string
  showToggle?: boolean
  showStatus?: boolean
  busy: boolean
  disabled?: boolean
  disabledTitle?: string
  status: CodexAuthStatus | null
  error: string
}>()

const emit = defineEmits<{
  toggle: [enabled: boolean]
  login: []
}>()
</script>

<template>
  <button
    v-if="showToggle !== false"
    type="button"
    class="official-auth-button"
    :class="{ active: enabled }"
    :disabled="busy || disabled"
    :title="disabled ? disabledTitle : undefined"
    @click="emit('toggle', !enabled)"
  >
    {{ enabled ? `${label || '官方授权'} ✓` : (label || '官方授权') }}
  </button>

  <div v-if="enabled && showStatus !== false" class="oauth-status-field">
    <span>OpenAI Account</span>
    <div class="oauth-status-card">
      <strong v-if="status?.authorized">已授权 {{ status.email || status.accountIdSuffix }}</strong>
      <strong v-else>未授权</strong>
      <small v-if="status?.planType">{{ status.planType }}</small>
      <small v-if="error || status?.error">{{ error || status?.error }}</small>
      <button type="button" :disabled="busy" @click="emit('login')">
        {{ status?.authorized ? '重新检测' : '登录 OpenAI' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.official-auth-button {
  white-space: nowrap;
  color: rgba(186, 230, 253, 0.95);
}

.official-auth-button.active {
  border-color: rgba(34, 197, 94, 0.55);
  color: rgba(187, 247, 208, 0.98);
  background: rgba(22, 101, 52, 0.25);
}

.oauth-status-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: rgba(226, 232, 240, 0.94);
  font-size: 12px;
}

.oauth-status-card {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 6px 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.5);
}

.oauth-status-card small {
  min-width: 0;
  flex: 1;
  color: rgba(148, 163, 184, 0.9);
  overflow-wrap: anywhere;
}
</style>
