<script setup lang="ts">
import { ref } from 'vue'
import type { CodexAuthStatus } from '../../settingsApi'
import {
  activateProviderAccount,
  addProviderApiKeyAccount,
  deleteProviderAccount,
} from '../../settingsApi'

const props = defineProps<{
  enabled: boolean
  label?: string
  showToggle?: boolean
  showStatus?: boolean
  oauthEnabled?: boolean
  oauthSupported?: boolean
  providerAuthId: string
  selectedAccountId?: string
  busy: boolean
  disabled?: boolean
  disabledTitle?: string
  status: CodexAuthStatus | null
  error: string
}>()

const emit = defineEmits<{
  toggle: [enabled: boolean]
  login: []
  status: [value: CodexAuthStatus]
  account: [accountId: string]
}>()

const apiKey = ref('')
const alias = ref('')
const identity = ref('')
const accountError = ref('')
const accountBusy = ref(false)

async function select(accountId: string) {
  if (!props.providerAuthId) return
  accountBusy.value = true
  accountError.value = ''
  try {
    emit('status', await activateProviderAccount(props.providerAuthId, accountId))
    emit('account', accountId)
  } catch (error) {
    accountError.value = String((error as Error)?.message || error)
  } finally {
    accountBusy.value = false
  }
}

async function remove(accountId: string) {
  if (!props.providerAuthId) return
  accountBusy.value = true
  accountError.value = ''
  try {
    emit('status', await deleteProviderAccount(props.providerAuthId, accountId))
    if (props.selectedAccountId === accountId) emit('account', '')
  } catch (error) {
    accountError.value = String((error as Error)?.message || error)
  } finally {
    accountBusy.value = false
  }
}

async function addApiKey() {
  const key = apiKey.value.trim()
  const accountIdentity = identity.value.trim() || alias.value.trim()
  if (!key || !accountIdentity || !props.providerAuthId) {
    accountError.value = 'API Key 和账号标识不能为空。'
    return
  }
  accountBusy.value = true
  accountError.value = ''
  try {
    const next = await addProviderApiKeyAccount(props.providerAuthId, {
      apiKey: key,
      alias: alias.value.trim(),
      identity: accountIdentity,
    })
    emit('status', next)
    if (next.activeAccountId) emit('account', next.activeAccountId)
    apiKey.value = ''
    alias.value = ''
    identity.value = ''
  } catch (error) {
    accountError.value = String((error as Error)?.message || error)
  } finally {
    accountBusy.value = false
  }
}
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
    <span>{{ providerAuthId || status?.provider || 'Provider' }} Accounts</span>
    <div class="oauth-status-card">
      <strong v-if="status?.authorized">已配置账号</strong>
      <strong v-else>尚无账号</strong>
      <small v-if="status?.planType">{{ status.planType }}</small>
      <small v-if="error || status?.error || accountError">{{ error || status?.error || accountError }}</small>
      <button
        v-if="oauthEnabled && oauthSupported"
        type="button"
        :disabled="busy || accountBusy"
        @click="emit('login')"
      >
        {{ status?.authorized ? '添加 OAuth 账号' : `登录 ${providerAuthId}` }}
      </button>
      <small v-if="status?.accounts?.length">{{ status.accounts.length }} 个账号</small>
    </div>

    <div v-if="!oauthEnabled" class="api-key-account-form">
      <input v-model="alias" placeholder="账号名称，例如：工作账号" autocomplete="off" />
      <input v-model="identity" placeholder="唯一标识，例如：work（留空则使用名称）" autocomplete="off" />
      <input v-model="apiKey" type="password" placeholder="API Key" autocomplete="new-password" />
      <button type="button" :disabled="accountBusy" @click="addApiKey">添加 API Key 账号</button>
    </div>

    <div v-if="status?.accounts?.length" class="oauth-account-list">
      <div v-for="account in status.accounts" :key="account.id" class="oauth-account-row">
        <span>{{ account.alias || account.identity || account.id }}</span>
        <small>
          {{ account.kind }}
          {{ selectedAccountId === account.id ? ' · 当前 Provider' : account.active ? ' · 全局活动' : '' }}
        </small>
        <button
          v-if="selectedAccountId !== account.id"
          type="button"
          :disabled="busy || accountBusy"
          @click="select(account.id)"
        >
          选择
        </button>
        <button type="button" class="danger" :disabled="busy || accountBusy" @click="remove(account.id)">移除</button>
      </div>
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
  gap: 7px;
  color: rgba(226, 232, 240, 0.94);
  font-size: 12px;
}

.oauth-status-card,
.oauth-account-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.5);
}

.oauth-status-card small,
.oauth-account-row > span {
  min-width: 0;
  flex: 1;
  overflow-wrap: anywhere;
}

.api-key-account-form {
  display: grid;
  grid-template-columns: minmax(120px, 0.7fr) minmax(140px, 1fr) minmax(180px, 1.4fr) auto;
  gap: 6px;
}

.api-key-account-form input {
  min-width: 0;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 7px;
  padding: 7px 8px;
  color: rgba(226, 232, 240, 0.96);
  background: rgba(2, 6, 23, 0.5);
}

.oauth-account-list {
  display: grid;
  gap: 5px;
}

.oauth-account-row > span {
  overflow: hidden;
  text-overflow: ellipsis;
}

.oauth-account-row .danger {
  color: rgba(254, 202, 202, 0.96);
}

@media (max-width: 900px) {
  .api-key-account-form {
    grid-template-columns: 1fr;
  }
}
</style>
