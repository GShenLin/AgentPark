<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  addRemote,
  deleteRemote,
  restartServer,
} from '../api'
import type { RemoteEndpoint } from '../apiTypes'
import ActionButton from './ActionButton.vue'
import DangerButton from './DangerButton.vue'
import FormCheckbox from './FormCheckbox.vue'
import FormSelect from './FormSelect.vue'
import FormTextInput from './FormTextInput.vue'
import LanguageSwitcher from './LanguageSwitcher.vue'
import { t } from '../i18n'

const props = defineProps<{
  activeView: 'board' | 'settings'
  leftCollapsed: boolean
  rightCollapsed: boolean
  canAccessLocalFiles: boolean
  canOpenSettings: boolean
  initialRemotes: RemoteEndpoint[]
}>()

const emit = defineEmits<{
  'update:activeView': [value: 'board' | 'settings']
  toggleLeft: []
  toggleRight: []
  error: [message: string]
}>()

const remoteEndpoints = ref<RemoteEndpoint[]>(props.initialRemotes)
const selectedRemoteId = ref('default')
const showRemoteForm = ref(false)
const remoteFormName = ref('')
const remoteFormHost = ref('')
const remoteFormPort = ref('8788')
const remoteFormPrivate = ref(false)
const isRestarting = ref(false)

const selectedRemote = computed(() => {
  return remoteEndpoints.value.find((remote) => remote.id === selectedRemoteId.value) || remoteEndpoints.value[0] || null
})

const selectedRemoteAddress = computed(() => {
  const remote = selectedRemote.value
  if (!remote) return '127.0.0.1:8788'
  return `${remote.host}:${remote.port}`
})

function remoteBaseUrl(remote: RemoteEndpoint) {
  return `http://${remote.host}:${remote.port}`
}

function selectRemote() {
  const remote = selectedRemote.value
  if (!remote) return
  if (remote.id === 'default') return
  window.open(remoteBaseUrl(remote), '_blank', 'noopener,noreferrer')
}

async function submitRemote() {
  const name = remoteFormName.value.trim()
  const host = remoteFormHost.value.trim()
  const portText = remoteFormPort.value.trim()
  if (!name || !host || !portText) {
    emit('error', t('topbar.remoteNameRequired'))
    return
  }
  if (!/^\d+$/.test(portText)) {
    emit('error', t('topbar.remotePortInvalid'))
    return
  }
  const port = Number(portText)
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
    emit('error', t('topbar.remotePortInvalid'))
    return
  }
  try {
    const res = await addRemote({ name, host, port, private: remoteFormPrivate.value })
    remoteEndpoints.value = res.remotes
    showRemoteForm.value = false
    remoteFormName.value = ''
    remoteFormHost.value = ''
    remoteFormPort.value = '8788'
    remoteFormPrivate.value = false
  } catch (e: any) {
    emit('error', String(e?.message || e))
  }
}

async function removeSelectedRemote() {
  const remote = selectedRemote.value
  if (!remote || remote.id === 'default') return
  try {
    const res = await deleteRemote(remote.id)
    remoteEndpoints.value = res.remotes
    selectedRemoteId.value = 'default'
  } catch (e: any) {
    emit('error', String(e?.message || e))
  }
}

async function restartWorkspace() {
  if (isRestarting.value) return
  isRestarting.value = true
  emit('error', '')
  try {
    await restartServer()
  } catch (e: any) {
    emit('error', String(e?.message || e))
    isRestarting.value = false
  }
}

</script>

<template>
  <header class="topbar">
    <div class="brand">{{ t('topbar.title') }}</div>
    <div class="remote-switcher">
      <span class="remote-label">{{ t('topbar.remote') }}</span>
      <FormSelect v-model="selectedRemoteId" class="remote-select" compact @change="selectRemote">
        <option v-for="remote in remoteEndpoints" :key="remote.id" :value="remote.id">
          {{ remote.name }} · {{ remote.host }}:{{ remote.port }}{{ remote.private ? ` · ${t('topbar.remotePrivate')}` : '' }}
        </option>
      </FormSelect>
      <span class="remote-address">{{ selectedRemoteAddress }}</span>
      <ActionButton compact @click="showRemoteForm = !showRemoteForm">{{ t('common.add') }}</ActionButton>
      <DangerButton compact :disabled="selectedRemoteId === 'default'" @click="removeSelectedRemote">{{ t('common.delete') }}</DangerButton>
    </div>
    <form v-if="showRemoteForm" class="remote-form" @submit.prevent="submitRemote" @click.stop>
      <FormTextInput v-model="remoteFormName" class="remote-input" compact :placeholder="t('common.name')" />
      <FormTextInput v-model="remoteFormHost" class="remote-input" compact :placeholder="t('topbar.ipHost')" />
      <FormTextInput
        v-model="remoteFormPort"
        class="remote-input port"
        compact
        type="number"
        inputmode="numeric"
        min="1"
        max="65535"
        step="1"
        :placeholder="t('topbar.port')"
      />
      <label class="remote-private">
        <FormCheckbox v-model="remoteFormPrivate" />
        <span>{{ t('topbar.remotePrivate') }}</span>
      </label>
      <ActionButton variant="primary" compact type="submit">{{ t('common.save') }}</ActionButton>
    </form>
    <div class="topbar-actions">
      <ActionButton v-if="props.activeView === 'board' && props.canAccessLocalFiles" compact @click="emit('toggleLeft')">
        {{ props.leftCollapsed ? t('topbar.showFiles') : t('topbar.hideFiles') }}
      </ActionButton>
      <ActionButton v-if="props.activeView === 'board'" compact @click="emit('toggleRight')">
        {{ props.rightCollapsed ? t('topbar.showMemory') : t('topbar.hideMemory') }}
      </ActionButton>
      <ActionButton class="restart" compact :disabled="isRestarting" @click="restartWorkspace">
        {{ isRestarting ? t('common.restarting') : t('common.restart') }}
      </ActionButton>
      <ActionButton
        v-if="props.canOpenSettings"
        class="settings"
        compact
        :class="{ active: props.activeView === 'settings' }"
        @click="emit('update:activeView', 'settings')"
      >
        {{ t('common.settings') }}
      </ActionButton>
      <LanguageSwitcher compact />
    </div>
  </header>
</template>

<style scoped>
.topbar {
  position: relative;
  z-index: 2000;
  overflow: visible;
  --form-control-border: var(--theme-panel-topbar-input-border, var(--border-light));
  --form-control-background: var(--theme-panel-topbar-input-background, var(--bg-primary));
  --form-control-text: var(--theme-panel-topbar-input-text, var(--text-primary));
  --form-control-focus: var(--theme-panel-topbar-button-active-text, var(--accent-blue));
  --ui-control-radius: 6px;
  --ui-button-background: var(--theme-panel-topbar-button-background, transparent);
  --ui-button-border: var(--theme-panel-topbar-button-border, transparent);
  --ui-button-text: var(--theme-panel-topbar-button-text, var(--text-secondary));
  --ui-button-hover-border: transparent;
  --ui-button-hover-background: var(--theme-panel-topbar-button-hover-background, var(--bg-hover));
  --ui-primary-border: var(--theme-panel-topbar-button-active-text, var(--accent-blue));
  --ui-primary-background: var(--theme-panel-topbar-button-active-background, var(--accent-blue-soft));
  --ui-primary-text: var(--theme-panel-topbar-button-active-text, var(--text-accent));
}

/* 远程连接切换器 */
.remote-switcher,
.remote-form {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

/* 远程表单弹窗 */
.remote-form {
  position: absolute;
  left: 360px;
  top: 52px;
  z-index: 30;
  padding: 12px;
  border: 1px solid var(--theme-panel-topbar-border-color, var(--border-light));
  border-radius: 10px;
  background: var(--theme-panel-topbar-background-color, rgba(30, 41, 59, 0.98));
  box-shadow: var(--shadow-xl);
  backdrop-filter: blur(20px);
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.remote-label,
.remote-address {
  color: var(--theme-panel-topbar-text-muted, var(--text-tertiary));
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}

.remote-private {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--theme-panel-topbar-text-secondary, var(--text-secondary));
  font-size: 12px;
  white-space: nowrap;
}

.remote-select,
.remote-input {
  min-width: 120px;
  max-width: 220px;
}

.remote-input.port {
  width: 74px;
  min-width: 74px;
}

/* 按钮区域 */
.topbar-actions {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

/* 重启按钮样式 */
.restart {
  color: #fcd34d;
}

.restart:hover {
  background: rgba(245, 158, 11, 0.15);
  color: #fcd34d;
}

/* 设置按钮样式 */
.settings {
  color: var(--theme-panel-topbar-button-text, var(--text-secondary));
}

.settings:hover {
  color: var(--theme-panel-topbar-button-hover-text, var(--text-primary));
}

.settings.active {
  background: var(--theme-panel-topbar-button-active-background, var(--accent-blue-soft));
  border-color: transparent;
  color: var(--theme-panel-topbar-button-active-text, var(--text-accent));
}
</style>
