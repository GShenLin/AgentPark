<script setup lang="ts">
import type { CodexAuthStatus } from '../../settingsApi'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'
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
    <FormSelect :model-value="providerType" @change="emit('field', 'type', $event)">
      <option value="">Unset</option>
      <option value="alpha_matting">alpha_matting</option>
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
    </FormSelect>
  </label>
  <label v-if="!['codex', 'oauth'].includes(authMode)">
    <span>Base URL</span>
    <FormTextInput :model-value="baseUrl" @update:model-value="emit('field', 'baseUrl', $event)" />
    <small v-if="authMode === 'none'">No credentials; the endpoint must use an HTTP loopback address.</small>
  </label>
  <label v-if="!['codex', 'oauth', 'none'].includes(authMode)">
    <span>API Key Name</span>
    <FormTextInput :model-value="apiKey" @update:model-value="emit('field', 'apiKey', $event)" />
    <small>References a key name defined in .auth/api-keys/aliases.json.</small>
  </label>
  <label v-if="!['codex', 'oauth'].includes(authMode) && showDoubaoSpeechAuth">
    <span>X-Api-Key Name</span>
    <FormTextInput :model-value="xApiKey" @update:model-value="emit('field', 'xApiKey', $event)" />
    <small>References the X-Api-Key value in .auth/api-keys/aliases.json for Doubao speech APIs.</small>
  </label>
  <label v-if="!['codex', 'oauth'].includes(authMode) && showDoubaoSpeechAuth">
    <span>Speech Access Key ID Name</span>
    <FormTextInput :model-value="speechAccessKeyId" @update:model-value="emit('field', 'speechAccessKeyId', $event)" />
    <small>References the Access Key ID in .auth/api-keys/aliases.json.</small>
  </label>
  <label v-if="!['codex', 'oauth'].includes(authMode) && showDoubaoSpeechAuth">
    <span>Speech Secret Access Key Name</span>
    <FormTextInput :model-value="speechSecretAccessKey" @update:model-value="emit('field', 'speechSecretAccessKey', $event)" />
    <small>References the Secret Access Key in .auth/api-keys/aliases.json.</small>
  </label>
  <ProviderOfficialAuthControl
    v-if="authMode !== 'none'"
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

small {
  color: rgba(148, 163, 184, 0.92);
}
</style>
