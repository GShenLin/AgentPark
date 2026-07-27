<script setup lang="ts">
import type { CodexAuthStatus } from '../../settingsApi'
import ProviderOfficialAuthControl from './ProviderOfficialAuthControl.vue'

defineProps<{
  providerType: string
  providerAuthId: string
  authMode: string
  authAccountId: string
  oauthSupported: boolean
  baseUrl: string
  apiKey: string
  xApiKey: string
  speechAccessKeyId: string
  speechSecretAccessKey: string
  showDoubaoSpeechAuth: boolean
  busy: boolean
  status: CodexAuthStatus | null
  error: string
}>()

const emit = defineEmits<{
  field: [key: string, value: string]
  officialAuth: [enabled: boolean]
  login: []
  status: [value: CodexAuthStatus]
  account: [accountId: string]
}>()
</script>

<template>
  <label>
    <span>Type</span>
    <select :value="providerType" @change="emit('field', 'type', ($event.target as HTMLSelectElement).value)">
      <option value="">Unset</option>
      <option value="agnes">agnes</option>
      <option value="openai">openai</option>
      <option value="claude">claude</option>
      <option value="deepseek">deepseek</option>
      <option value="doubao">doubao</option>
      <option value="gemini">gemini</option>
      <option value="grok">grok</option>
      <option value="kimi">kimi</option>
      <option value="zhipu">zhipu</option>
      <option value="hyper3d">hyper3d</option>
    </select>
  </label>
  <label v-if="!['codex', 'oauth'].includes(authMode)">
    <span>Base URL</span>
    <input :value="baseUrl" @input="emit('field', 'baseUrl', ($event.target as HTMLInputElement).value)" />
  </label>
  <label v-if="!['codex', 'oauth'].includes(authMode)">
    <span>API Key Name</span>
    <input :value="apiKey" @input="emit('field', 'apiKey', ($event.target as HTMLInputElement).value)" />
    <small>References a key name defined in .auth/api-keys/aliases.json.</small>
  </label>
  <label v-if="!['codex', 'oauth'].includes(authMode) && showDoubaoSpeechAuth">
    <span>X-Api-Key Name</span>
    <input :value="xApiKey" @input="emit('field', 'xApiKey', ($event.target as HTMLInputElement).value)" />
    <small>References the X-Api-Key value in .auth/api-keys/aliases.json for Doubao speech APIs.</small>
  </label>
  <label v-if="!['codex', 'oauth'].includes(authMode) && showDoubaoSpeechAuth">
    <span>Speech Access Key ID Name</span>
    <input :value="speechAccessKeyId" @input="emit('field', 'speechAccessKeyId', ($event.target as HTMLInputElement).value)" />
    <small>References the Access Key ID in .auth/api-keys/aliases.json.</small>
  </label>
  <label v-if="!['codex', 'oauth'].includes(authMode) && showDoubaoSpeechAuth">
    <span>Speech Secret Access Key Name</span>
    <input :value="speechSecretAccessKey" @input="emit('field', 'speechSecretAccessKey', ($event.target as HTMLInputElement).value)" />
    <small>References the Secret Access Key in .auth/api-keys/aliases.json.</small>
  </label>
  <ProviderOfficialAuthControl
    :enabled="true"
    :show-toggle="false"
    :show-status="true"
    :oauth-enabled="['codex', 'oauth'].includes(authMode)"
    :oauth-supported="oauthSupported"
    :provider-auth-id="providerAuthId"
    :selected-account-id="authAccountId"
    :busy="busy"
    :status="status"
    :error="error"
    @toggle="emit('officialAuth', $event)"
    @login="emit('login')"
    @status="emit('status', $event)"
    @account="emit('account', $event)"
  />
</template>

<style scoped>
label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: rgba(226, 232, 240, 0.94);
  font-size: 12px;
}

input,
select {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  padding: 8px 9px;
  color: rgba(226, 232, 240, 0.96);
  background: rgba(2, 6, 23, 0.5);
  font: inherit;
}

small {
  color: rgba(148, 163, 184, 0.92);
}
</style>
