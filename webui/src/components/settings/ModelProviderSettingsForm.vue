<script setup lang="ts">
import SettingsFieldGroup from './SettingsFieldGroup.vue'
import SettingsDetailLayout from './SettingsDetailLayout.vue'
import { useSettingsDetail } from './settingsNavigation'
import { computed, onMounted, ref, watch } from 'vue'
import { getProviderLimits, type ProviderLimitDocument } from '../../settingsApi'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import ExpandableTextarea from '../ExpandableTextarea.vue'
import FormCheckbox from '../FormCheckbox.vue'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'
import SelectionButton from '../SelectionButton.vue'
import ProviderAuthFields from './ProviderAuthFields.vue'
import DoubaoSpeechManagementPanel from './DoubaoSpeechManagementPanel.vue'
import { applyResponsesApiDefaults } from './providerConfigDefaults'
import SupportModeMultiSelect from './SupportModeMultiSelect.vue'
import { useCodexOfficialAuth } from './useCodexOfficialAuth'
import { t } from '../../i18n'

const { detailOpen, openDetail, closeDetail } = useSettingsDetail()

const props = defineProps<{
  data: Record<string, unknown>
}>()

const emit = defineEmits<{
  'update:data': [value: Record<string, unknown>]
  'provider-duplicated': [sourceProviderId: string, targetProviderId: string]
  'provider-id-changed': [previousProviderId: string, nextProviderId: string]
  'provider-deleted': [providerId: string]
  'provider-model-added': [providerId: string, modelId: string]
}>()

const selectedProviderId = ref('')
const editableProviderId = ref('')
const providerIdError = ref('')
const newProviderId = ref('')
const providerSearch = ref('')
const filteredProviderIds = computed(() => providerIds.value.filter(id => `${id} ${providerModelSummary(id)}`.toLowerCase().includes(providerSearch.value.trim().toLowerCase())))
const providerLimits = ref<ProviderLimitDocument | null>(null)
const limitWarning = ref('')
const addingModelId = ref(false)
const newModelId = ref('')
const modelIdError = ref('')
const pendingManualModelIds = ref<Record<string, string[]>>({})
const {
  status: codexAuthStatus,
  busy: codexAuthBusy,
  error: codexAuthError,
  loadStatus: loadCodexAuthStatus,
  beginLogin: beginOfficialLogin,
  setStatus: setProviderAuthStatus,
} = useCodexOfficialAuth()

const providers = computed<Record<string, Record<string, unknown>>>(() => {
  const value = props.data.providers
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, Record<string, unknown>>
    : {}
})

const providerIds = computed(() => Object.keys(providers.value))
const selectedProvider = computed(() => providers.value[selectedProviderId.value] || null)
const isDoubaoAudioProvider = computed(() => (
  String(selectedProvider.value?.type || '').trim().toLowerCase() === 'doubao'
  && Array.isArray(selectedProvider.value?.supportmode)
  && selectedProvider.value.supportmode.includes('audio_generation')
))
const selectedLimit = computed(() => providerLimits.value?.providers?.[selectedProviderId.value] || null)
const availableModelIds = computed(() => {
  const discovered = selectedLimit.value?.available_model_ids || []
  const pending = pendingManualModelIds.value[selectedProviderId.value] || []
  return [...new Set([...discovered, ...pending])]
})
const providerModelIds = computed(() => {
  const rawModels = selectedProvider.value?.models
  const rawModel = selectedProvider.value?.model
  const values = Array.isArray(rawModels)
    ? rawModels
    : Array.isArray(rawModel) ? rawModel : [rawModel]
  return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))]
})
const activeLimitWarnings = computed(() => {
  const warnings: string[] = []
  const provider = selectedProvider.value
  if (!provider) return warnings
  for (const key of Object.keys(provider)) {
    const warning = unsupportedWarningFor(key, provider[key])
    if (warning && !warnings.includes(warning)) warnings.push(warning)
  }
  return warnings
})
const isOpenAIProvider = computed(() => stringValue('type').trim().toLowerCase() === 'openai')
const oauthProviderType = computed(() => {
  const providerType = stringValue('type').trim().toLowerCase()
  if (providerType === 'claude') return 'anthropic'
  if (providerType === 'grok') return 'xai'
  return ['openai', 'kimi'].includes(providerType) ? providerType : ''
})
const officialAuthEnabled = computed(() => ['codex', 'oauth'].includes(stringValue('authMode')))
const providerAuthId = computed(() => (
  stringValue('authProvider').trim().toLowerCase()
  || oauthProviderType.value
  || stringValue('type').trim().toLowerCase()
))

watch(
  providerIds,
  (ids) => {
    if (!ids.includes(selectedProviderId.value)) {
      selectedProviderId.value = ids[0] || ''
    }
  },
  { immediate: true },
)

watch(
  selectedProviderId,
  (providerId) => {
    editableProviderId.value = providerId
    providerIdError.value = ''
  },
  { immediate: true },
)

watch(
  providerAuthId,
  (providerId) => {
    if (providerId) void loadCodexAuthStatus(providerId)
  },
  { immediate: true },
)

function cloneData() {
  return JSON.parse(JSON.stringify(props.data || {})) as Record<string, unknown>
}

function emitProvider(providerId: string, nextProvider: Record<string, unknown>) {
  const next = cloneData()
  const nextProviders = {
    ...(next.providers && typeof next.providers === 'object' && !Array.isArray(next.providers)
      ? next.providers as Record<string, Record<string, unknown>>
      : {}),
    [providerId]: nextProvider,
  }
  next.providers = nextProviders
  emit('update:data', next)
}

function parseTextList(value: string) {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function textList(value: unknown) {
  if (!Array.isArray(value)) return ''
  return value.map((item) => String(item)).join('\n')
}

function listValue(key: string) {
  const value = selectedProvider.value?.[key]
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item || '').trim()).filter(Boolean)
}

function stringValue(key: string) {
  return String(selectedProvider.value?.[key] ?? '')
}

function providerModelSummary(providerId: string) {
  const provider = providers.value[providerId]
  const model = Array.isArray(provider?.models) ? provider.models : provider?.model
  if (Array.isArray(model)) return model.map((value) => String(value || '').trim()).filter(Boolean).join(', ')
  return String(model || '').trim()
}

function booleanValue(key: string) {
  return selectedProvider.value?.[key] === true
}

function numberValue(key: string) {
  const value = selectedProvider.value?.[key]
  if (value === null || value === undefined || value === '') return ''
  return String(value)
}

function currentModelValue() {
  const model = selectedProvider.value?.model
  if (Array.isArray(model)) return String(model[0] || '').trim()
  return stringValue('model').trim()
}

function setProviderModels(modelIds: string[]) {
  const normalized = [...new Set(modelIds.map((value) => String(value || '').trim()).filter(Boolean))]
  setField('model', normalized)
  const current = currentModelValue()
  if (!current || !normalized.includes(current)) setField('model', normalized[0] || '')
}

function updateProviderModel(index: number, value: string) {
  const next = [...providerModelIds.value]
  next[index] = value
  setProviderModels(next)
}

function removeProviderModel(index: number) {
  if (providerModelIds.value.length <= 1) return
  setProviderModels(providerModelIds.value.filter((_, itemIndex) => itemIndex !== index))
}

function openAddModelForm() {
  addingModelId.value = true
  newModelId.value = ''
  modelIdError.value = ''
}

function closeAddModelForm() {
  addingModelId.value = false
  newModelId.value = ''
  modelIdError.value = ''
}

function addModelId() {
  const providerId = selectedProviderId.value
  const modelId = newModelId.value.trim()
  if (!providerId || !modelId) {
    modelIdError.value = t('provider.modelIdRequired')
    return
  }
  if (!providerModelIds.value.includes(modelId)) {
    setProviderModels([...providerModelIds.value, modelId])
  }
  if (!availableModelIds.value.includes(modelId)) {
    pendingManualModelIds.value = {
      ...pendingManualModelIds.value,
      [providerId]: [...(pendingManualModelIds.value[providerId] || []), modelId],
    }
    emit('provider-model-added', providerId, modelId)
  }
  if (!currentModelValue()) setField('model', modelId)
  closeAddModelForm()
}

function setField(key: string, value: unknown) {
  if (!selectedProviderId.value || !selectedProvider.value) return
  const provider = { ...selectedProvider.value }
  limitWarning.value = unsupportedWarningFor(key, value)
  if (value === '' || value === null || value === undefined) {
    delete provider[key]
  } else {
    provider[key] = value
  }
  if (key === 'responsesApi' && value === true) {
    applyResponsesApiDefaults(provider)
  }
  emitProvider(selectedProviderId.value, provider)
}

function setOfficialAuthEnabled(enabled: boolean) {
  if (!selectedProviderId.value || !selectedProvider.value || !oauthProviderType.value) return
  const provider = { ...selectedProvider.value }
  if (enabled) {
    provider.authMode = oauthProviderType.value === 'openai'
      ? 'codex'
      : 'oauth'
    provider.authProvider = oauthProviderType.value
    delete provider.apiKey
    if (oauthProviderType.value === 'openai') {
      provider.responsesApi = true
      provider.baseUrl = 'https://chatgpt.com/backend-api/codex'
      applyResponsesApiDefaults(provider)
    } else if (oauthProviderType.value === 'anthropic') {
      provider.baseUrl = 'https://api.anthropic.com/v1'
    } else if (oauthProviderType.value === 'kimi') {
      provider.baseUrl ||= 'https://api.kimi.com/coding/v1'
    } else if (oauthProviderType.value === 'xai') {
      provider.baseUrl ||= 'https://api.x.ai/v1'
    }
  } else {
    provider.authMode = 'api_key'
    delete provider.authProvider
    if (oauthProviderType.value === 'openai') delete provider.baseUrl
  }
  emitProvider(selectedProviderId.value, provider)
  if (enabled) void beginOfficialLogin(oauthProviderType.value)
}

function triggerOfficialAuth() {
  setOfficialAuthEnabled(!officialAuthEnabled.value)
}

function setNumberField(key: string, raw: string) {
  const text = String(raw || '').trim()
  setField(key, text ? Number(text) : '')
}

function addProvider() {
  const id = newProviderId.value.trim()
  if (!id || providers.value[id]) return
  const next = cloneData()
  next.providers = {
    ...providers.value,
    [id]: {
      type: 'openai',
      model: '',
      supportmode: ['chat'],
      private: false,
    },
  }
  emit('update:data', next)
  selectedProviderId.value = id
  newProviderId.value = ''
  openDetail()
}

function setProviderId(rawProviderId: string) {
  editableProviderId.value = rawProviderId
  const currentId = selectedProviderId.value
  const nextId = rawProviderId.trim()
  if (!currentId || !selectedProvider.value) return
  if (!nextId) {
    providerIdError.value = 'Provider ID is required.'
    return
  }
  if (nextId === currentId) {
    providerIdError.value = ''
    return
  }
  if (providers.value[nextId]) {
    providerIdError.value = `Provider ID '${nextId}' already exists.`
    return
  }

  const next = cloneData()
  next.providers = Object.fromEntries(
    Object.entries(providers.value).map(([providerId, provider]) => (
      providerId === currentId ? [nextId, provider] : [providerId, provider]
    )),
  )
  const currentLimit = providerLimits.value?.providers?.[currentId]
  if (providerLimits.value && currentLimit) {
    const renamedLimit = JSON.parse(JSON.stringify(currentLimit)) as typeof currentLimit
    renamedLimit.provider_id = nextId
    const nextLimits = { ...providerLimits.value.providers }
    delete nextLimits[currentId]
    nextLimits[nextId] = renamedLimit
    providerLimits.value = { ...providerLimits.value, providers: nextLimits }
  }
  const currentPendingModels = pendingManualModelIds.value[currentId]
  if (currentPendingModels) {
    const nextPending = { ...pendingManualModelIds.value }
    nextPending[nextId] = currentPendingModels
    delete nextPending[currentId]
    pendingManualModelIds.value = nextPending
  }
  emit('update:data', next)
  emit('provider-id-changed', currentId, nextId)
  selectedProviderId.value = nextId
}

function normalizeProviderId() {
  editableProviderId.value = selectedProviderId.value
  providerIdError.value = ''
}

function duplicateProvider() {
  const sourceId = selectedProviderId.value
  const sourceProvider = selectedProvider.value
  if (!sourceId || !sourceProvider) return

  let duplicateId = `${sourceId}1`
  while (providers.value[duplicateId]) {
    duplicateId += '1'
  }

  const next = cloneData()
  next.providers = {
    ...providers.value,
    [duplicateId]: JSON.parse(JSON.stringify(sourceProvider)) as Record<string, unknown>,
  }
  const sourceLimit = providerLimits.value?.providers?.[sourceId]
  if (providerLimits.value && sourceLimit) {
    const duplicateLimit = JSON.parse(JSON.stringify(sourceLimit)) as typeof sourceLimit
    duplicateLimit.provider_id = duplicateId
    duplicateLimit.type = String(sourceProvider.type || duplicateLimit.type || '').trim()
    duplicateLimit.model = String(sourceProvider.model || duplicateLimit.model || '').trim()
    providerLimits.value = {
      ...providerLimits.value,
      providers: {
        ...providerLimits.value.providers,
        [duplicateId]: duplicateLimit,
      },
    }
  }
  const sourcePendingModels = pendingManualModelIds.value[sourceId] || []
  if (sourcePendingModels.length) {
    pendingManualModelIds.value = {
      ...pendingManualModelIds.value,
      [duplicateId]: [...sourcePendingModels],
    }
    for (const modelId of sourcePendingModels) {
      emit('provider-model-added', duplicateId, modelId)
    }
  }
  emit('update:data', next)
  emit('provider-duplicated', sourceId, duplicateId)
  selectedProviderId.value = duplicateId
}

function deleteProvider() {
  const id = selectedProviderId.value
  if (!id) return
  const next = cloneData()
  const nextProviders = { ...providers.value }
  delete nextProviders[id]
  next.providers = nextProviders
  if (providerLimits.value?.providers?.[id]) {
    const nextLimits = { ...providerLimits.value.providers }
    delete nextLimits[id]
    providerLimits.value = { ...providerLimits.value, providers: nextLimits }
  }
  if (pendingManualModelIds.value[id]) {
    const nextPending = { ...pendingManualModelIds.value }
    delete nextPending[id]
    pendingManualModelIds.value = nextPending
  }
  emit('update:data', next)
  emit('provider-deleted', id)
  selectedProviderId.value = Object.keys(nextProviders)[0] || ''
}

function unsupportedWarningFor(key: string, value: unknown) {
  const limit = selectedLimit.value
  if (!limit) return ''
  if (limit.accessible === false) {
    return `Provider '${selectedProviderId.value}' is unavailable: ${limit.access_error || 'access test failed'}`
  }
  if (key === 'responsesApi' || key === 'responsesReplayReasoningItems') {
    if (key !== 'responsesApi' && (value === '' || value === null || value === undefined)) return ''
    if (key === 'responsesApi' && value !== true) return ''
    return featureUnsupportedWarning('responses_api')
  }
  if (key === 'reasoningEffort') {
    const text = String(value || '').trim()
    if (!text) return ''
    return valueUnsupportedWarning('reasoning_effort', text)
  }
  if (key === 'thinking') {
    const text = String(value || '').trim()
    if (!text) return ''
    return valueUnsupportedWarning('thinking', text)
  }
  if (key === 'webSearchSources' || key === 'webSearchMaxKeyword' || key === 'webSearchLimit') {
    const hasValue = Array.isArray(value) ? value.length > 0 : value !== '' && value !== null && value !== undefined
    if (!hasValue) return ''
    return featureUnsupportedWarning('web_search')
  }
  return ''
}

function featureUnsupportedWarning(featureKey: string) {
  const feature = selectedLimit.value?.features?.[featureKey]
  if (!feature || feature.supported) return ''
  return `${selectedProviderId.value}.${featureKey} is not supported: ${feature.reason || 'not supported by ProviderLimit.json'}`
}

function valueUnsupportedWarning(featureKey: string, value: string) {
  const feature = selectedLimit.value?.features?.[featureKey]
  const valueFeature = feature?.values?.[value]
  if (valueFeature && valueFeature.supported === false) {
    return `${selectedProviderId.value}.${featureKey}.${value} is not supported: ${valueFeature.reason || 'not supported by ProviderLimit.json'}`
  }
  if (feature && feature.supported === false) {
    return `${selectedProviderId.value}.${featureKey} is not supported: ${feature.reason || 'not supported by ProviderLimit.json'}`
  }
  return ''
}

async function loadProviderLimits() {
  try {
    providerLimits.value = await getProviderLimits()
  } catch {
    providerLimits.value = null
  }
}

onMounted(() => {
  void loadProviderLimits()
})
</script>

<template>
  <SettingsDetailLayout class="provider-settings" :detail-open="detailOpen" @back="closeDetail">
    <template #list>
      <aside class="settings-split__side">
        <FormTextInput v-model="providerSearch" type="search" :placeholder="t('settings.searchProviders')" :aria-label="t('settings.searchProviders')" />
        <div class="provider-add">
          <FormTextInput :aria-label="t('provider.newId')" v-model="newProviderId" :placeholder="t('provider.newId')" @keydown.enter.prevent="addProvider" />
          <ActionButton compact @click="addProvider">{{ t('common.add') }}</ActionButton>
        </div>
        <div class="settings-split__items">
          <SelectionButton
            v-for="providerId in filteredProviderIds"
            :key="providerId"
            class="settings-list-item"
            stacked
            :active="selectedProviderId === providerId"
            @click="selectedProviderId = providerId; openDetail()"
          >
            {{ providerId }}
            <template #detail>{{ providerModelSummary(providerId) || providers[providerId]?.type || '' }}</template>
          </SelectionButton>
        </div>
      </aside>
    </template>

    <section v-if="selectedProvider" class="provider-form settings-split__detail">
      <div class="form-head">
        <label class="provider-id-field">
          <span>{{ t('provider.id') }}</span>
          <FormTextInput
            :model-value="editableProviderId"
            :class="{ invalid: providerIdError }"
            autocomplete="off"
            spellcheck="false"
            @update:model-value="setProviderId($event)"
            @blur="normalizeProviderId"
          />
          <small v-if="providerIdError" class="field-error">{{ providerIdError }}</small>
          <small v-else>{{ t('provider.fields') }}</small>
        </label>
        <div class="form-head-actions">
          <ActionButton
            class="oauth-button"
            :class="{ active: oauthProviderType && officialAuthEnabled }"
            :disabled="codexAuthBusy || !oauthProviderType"
            :title="oauthProviderType ? `切换当前 Provider 的 ${oauthProviderType} 官方授权` : '该 Provider 暂无官方授权协议实现，可使用 API Key 多账号'"
            @click="triggerOfficialAuth"
          >
            {{ officialAuthEnabled ? 'OAuth ✓' : 'OAuth' }}
          </ActionButton>
          <ActionButton compact @click="duplicateProvider">{{ t('provider.duplicate') }}</ActionButton>
          <DangerButton @click="deleteProvider">{{ t('common.delete') }}</DangerButton>
        </div>
      </div>

      <div v-if="limitWarning || activeLimitWarnings.length" class="limit-warning">
        <strong>ProviderLimit</strong>
        <span>{{ limitWarning || activeLimitWarnings[0] }}</span>
      </div>

      <SettingsFieldGroup :title="t('settings.providerConnection')" expanded>
      <div class="form-grid">
        <ProviderAuthFields
          :provider-type="stringValue('type')"
          :provider-auth-id="providerAuthId"
          :auth-mode="stringValue('authMode') || 'api_key'"
          :auth-account-id="stringValue('authAccountId')"
          :oauth-supported="Boolean(oauthProviderType)"
          :base-url="stringValue('baseUrl')"
          :api-key="stringValue('apiKey')"
          :x-api-key="stringValue('xApiKey')"
          :speech-access-key-id="stringValue('speechAccessKeyId')"
          :speech-secret-access-key="stringValue('speechSecretAccessKey')"
          :show-doubao-speech-auth="isDoubaoAudioProvider"
          :busy="codexAuthBusy"
          :status="codexAuthStatus"
          :error="codexAuthError"
          @field="setField"
          @official-auth="setOfficialAuthEnabled"
          @login="beginOfficialLogin(oauthProviderType || 'openai')"
          @status="setProviderAuthStatus"
          @account="setField('authAccountId', $event)"
        />
        <div class="model-field">
          <span>{{ t('provider.models') }}</span>
          <div class="model-allowlist">
            <div v-for="(modelId, modelIndex) in providerModelIds" :key="`${modelId}-${modelIndex}`" class="model-id-row">
              <FormTextInput
                :model-value="modelId"
                :placeholder="t('provider.modelId')"
                autocomplete="off"
                spellcheck="false"
                @update:model-value="updateProviderModel(modelIndex, $event)"
              />
              <ActionButton compact :disabled="providerModelIds.length <= 1" @click="removeProviderModel(modelIndex)">×</ActionButton>
            </div>
            <span v-if="!providerModelIds.length" class="model-empty">{{ t('provider.noModels') }}</span>
            <ActionButton compact @click="openAddModelForm">{{ t('common.add') }}</ActionButton>
          </div>
          <div v-if="addingModelId" class="model-add-form">
            <FormTextInput
              v-model="newModelId"
              :placeholder="t('provider.modelId')"
              autocomplete="off"
              spellcheck="false"
              @keydown.enter.prevent="addModelId"
              @keydown.escape.prevent="closeAddModelForm"
            />
            <div class="model-add-actions">
              <ActionButton variant="primary" @click="addModelId">{{ t('common.add') }}</ActionButton>
              <ActionButton @click="closeAddModelForm">{{ t('common.cancel') }}</ActionButton>
            </div>
          </div>
          <small v-if="modelIdError" class="model-id-error">{{ modelIdError }}</small>
          <small v-else>{{ t('provider.modelsHelp') }}</small>
        </div>
        <label class="form-field-wide">
          <span>{{ t('provider.description') }}</span>
          <ExpandableTextarea
            :model-value="stringValue('description')"
            :title="t('provider.description')"
            :aria-label="t('provider.description')"
            :rows="3"
            @update:model-value="setField('description', $event)"
          />
        </label>
      </div>
      </SettingsFieldGroup>
      <SettingsFieldGroup :title="t('settings.providerLimits')">
      <div class="form-grid">
        <label>
          <span>{{ t('provider.timeout') }}</span>
          <FormTextInput :model-value="numberValue('timeoutMs')" type="number" min="1" @update:model-value="setNumberField('timeoutMs', $event)" />
        </label>
        <label>
          <span>{{ t('provider.concurrency') }}</span>
          <FormTextInput :model-value="numberValue('concurrencyLimit')" type="number" min="1" :placeholder="t('provider.unlimited')" @update:model-value="setNumberField('concurrencyLimit', $event)" />
        </label>
        <label>
          <span>{{ t('provider.rpm') }}</span>
          <FormTextInput :model-value="numberValue('rpmLimit')" type="number" min="1" :placeholder="t('provider.unlimited')" @update:model-value="setNumberField('rpmLimit', $event)" />
        </label>
        <label>
          <span>{{ t('provider.tpm') }}</span>
          <FormTextInput :model-value="numberValue('tpmLimit')" type="number" min="1" :placeholder="t('provider.unlimited')" @update:model-value="setNumberField('tpmLimit', $event)" />
        </label>
        <label>
          <span>{{ t('provider.maxTokens') }}</span>
          <FormTextInput :model-value="numberValue('maxTokens')" type="number" min="1" @update:model-value="setNumberField('maxTokens', $event)" />
        </label>
        <label>
          <span>{{ t('provider.reasoningEffort') }}</span>
          <FormSelect :model-value="stringValue('reasoningEffort')" @change="setField('reasoningEffort', $event)">
            <option value="">{{ t('defaults.unset') }}</option>
            <option value="minimal">minimal</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="xhigh">xhigh</option>
            <option value="max">max</option>
            <option value="auto">auto</option>
          </FormSelect>
        </label>
        <label>
          <span>{{ t('provider.reasoningSummary') }}</span>
          <FormSelect :model-value="stringValue('reasoningSummary')" @change="setField('reasoningSummary', $event)">
            <option value="">{{ t('defaults.unset') }}</option>
            <option value="auto">auto</option>
            <option value="concise">concise</option>
            <option value="detailed">detailed</option>
            <option value="disabled">disabled</option>
          </FormSelect>
        </label>
        <label>
          <span>{{ t('provider.thinking') }}</span>
          <FormSelect :model-value="stringValue('thinking')" @change="setField('thinking', $event)">
            <option value="">{{ t('defaults.unset') }}</option>
            <option value="enabled">enabled</option>
            <option value="disabled">disabled</option>
            <option value="auto">auto</option>
          </FormSelect>
        </label>
      </div>

      </SettingsFieldGroup>

      <DoubaoSpeechManagementPanel
        v-if="isDoubaoAudioProvider"
        :provider-id="selectedProviderId"
      />

      <SettingsFieldGroup :title="t('settings.providerProtocol')">
      <div class="switch-grid">
        <label class="switch-field" :title="t('provider.privateHelp')"><span>{{ t('provider.private') }}</span><FormCheckbox :model-value="booleanValue('private')" @update:model-value="setField('private', $event)" /></label>
        <label class="switch-field"><span>{{ t('provider.responsesApi') }}</span><FormCheckbox :model-value="booleanValue('responsesApi')" @update:model-value="setField('responsesApi', $event)" /></label>
        <label v-if="booleanValue('responsesApi')" class="switch-field"><span>{{ t('provider.responsesWebSocket') }}</span><FormCheckbox :model-value="booleanValue('responsesWebSocket')" @update:model-value="setField('responsesWebSocket', $event)" /></label>
        <label v-if="isOpenAIProvider && booleanValue('responsesApi')" class="switch-field"><span>{{ t('provider.fastMode') }}</span><FormCheckbox :model-value="booleanValue('fastMode')" @update:model-value="setField('fastMode', $event)" /></label>
        <label class="switch-field"><span>{{ t('provider.replayReasoning') }}</span><FormCheckbox :model-value="booleanValue('responsesReplayReasoningItems')" @update:model-value="setField('responsesReplayReasoningItems', $event)" /></label>
        <label class="switch-field"><span>{{ t('provider.toolCompaction') }}</span><FormCheckbox :model-value="booleanValue('toolContextCompactionEnabled')" @update:model-value="setField('toolContextCompactionEnabled', $event)" /></label>
        <label class="switch-field"><span>{{ t('provider.itemStreaming') }}</span><FormCheckbox :model-value="booleanValue('responsesItemLevelStreaming')" @update:model-value="setField('responsesItemLevelStreaming', $event)" /></label>
      </div>

      </SettingsFieldGroup>
      <SettingsFieldGroup :title="t('settings.providerTools')">
      <div class="form-grid">
        <label class="dropdown-field">
          <span>{{ t('provider.supportModes') }}</span>
          <SupportModeMultiSelect
            :selected-values="listValue('supportmode')"
            @update:selected-values="setField('supportmode', $event)"
          />
        </label>
        <label>
          <span>{{ t('provider.webSearchSources') }}</span>
          <ExpandableTextarea
            :model-value="textList(selectedProvider.webSearchSources)"
            :title="t('provider.webSearchSources')"
            :aria-label="t('provider.webSearchSources')"
            :rows="3"
            @update:model-value="setField('webSearchSources', parseTextList($event))"
          />
        </label>
        <label>
          <span>{{ t('provider.webSearchKeyword') }}</span>
          <FormTextInput :model-value="numberValue('webSearchMaxKeyword')" type="number" min="1" @update:model-value="setNumberField('webSearchMaxKeyword', $event)" />
        </label>
        <label>
          <span>{{ t('provider.webSearchLimit') }}</span>
          <FormTextInput :model-value="numberValue('webSearchLimit')" type="number" min="1" @update:model-value="setNumberField('webSearchLimit', $event)" />
        </label>
        <label>
          <span>{{ t('provider.compactionCalls') }}</span>
          <FormTextInput :model-value="numberValue('toolContextCompactionEveryToolCalls')" type="number" min="0" @update:model-value="setNumberField('toolContextCompactionEveryToolCalls', $event)" />
        </label>
        <label>
          <span>{{ t('provider.compactionInput') }}</span>
          <FormTextInput :model-value="numberValue('toolContextCompactionInputTokens')" type="number" min="0" @update:model-value="setNumberField('toolContextCompactionInputTokens', $event)" />
        </label>
        <label>
          <span>{{ t('provider.compactionOutput') }}</span>
          <FormTextInput :model-value="numberValue('toolContextCompactionOutputTokens')" type="number" min="0" @update:model-value="setNumberField('toolContextCompactionOutputTokens', $event)" />
        </label>
        <label>
          <span>{{ t('provider.toolResultChars') }}</span>
          <FormTextInput :model-value="numberValue('toolResultSubmissionMaxChars')" type="number" min="1" @update:model-value="setNumberField('toolResultSubmissionMaxChars', $event)" />
        </label>
      </div>
      </SettingsFieldGroup>
    </section>
  </SettingsDetailLayout>
</template>

<style scoped src="./ModelProviderSettingsForm.css"></style>
