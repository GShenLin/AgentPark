<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { getProviderLimits, type ProviderLimitDocument } from '../../settingsApi'
import ProviderAuthFields from './ProviderAuthFields.vue'
import DoubaoSpeechManagementPanel from './DoubaoSpeechManagementPanel.vue'
import { applyResponsesApiDefaults } from './providerConfigDefaults'
import SupportModeMultiSelect from './SupportModeMultiSelect.vue'
import { useCodexOfficialAuth } from './useCodexOfficialAuth'

const props = defineProps<{
  data: Record<string, unknown>
}>()

const emit = defineEmits<{
  'update:data': [value: Record<string, unknown>]
}>()

const selectedProviderId = ref('')
const editableProviderId = ref('')
const providerIdError = ref('')
const newProviderId = ref('')
const providerLimits = ref<ProviderLimitDocument | null>(null)
const limitWarning = ref('')
const {
  status: codexAuthStatus,
  busy: codexAuthBusy,
  error: codexAuthError,
  loadStatus: loadCodexAuthStatus,
  beginLogin: beginOfficialLogin,
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
const availableModelIds = computed(() => selectedLimit.value?.available_model_ids || [])
const modelOptions = computed(() => {
  const current = currentModelValue()
  const ids = availableModelIds.value
    .map((modelId) => String(modelId || '').trim())
    .filter(Boolean)
  return current && !ids.includes(current) ? [current, ...ids] : ids
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

function booleanValue(key: string) {
  return selectedProvider.value?.[key] === true
}

function numberValue(key: string) {
  const value = selectedProvider.value?.[key]
  if (value === null || value === undefined || value === '') return ''
  return String(value)
}

function currentModelValue() {
  return stringValue('model').trim()
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
  if (!selectedProviderId.value || !selectedProvider.value || !isOpenAIProvider.value) return
  const provider = { ...selectedProvider.value }
  if (enabled) {
    provider.authMode = 'codex'
    provider.responsesApi = true
    provider.baseUrl = 'https://chatgpt.com/backend-api/codex'
    delete provider.apiKey
    applyResponsesApiDefaults(provider)
  } else {
    provider.authMode = 'api_key'
    delete provider.baseUrl
  }
  emitProvider(selectedProviderId.value, provider)
  if (enabled) void beginOfficialLogin()
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
  emit('update:data', next)
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
  emit('update:data', next)
  selectedProviderId.value = duplicateId
}

function deleteProvider() {
  const id = selectedProviderId.value
  if (!id) return
  const next = cloneData()
  const nextProviders = { ...providers.value }
  delete nextProviders[id]
  next.providers = nextProviders
  emit('update:data', next)
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
  void loadCodexAuthStatus()
})
</script>

<template>
  <div class="provider-settings">
    <aside class="provider-list">
      <button
        v-for="providerId in providerIds"
        :key="providerId"
        type="button"
        class="provider-item"
        :class="{ active: selectedProviderId === providerId }"
        @click="selectedProviderId = providerId"
      >
        <span>{{ providerId }}</span>
        <small>{{ providers[providerId]?.model || providers[providerId]?.type || '' }}</small>
      </button>
      <div class="provider-add">
        <input v-model="newProviderId" placeholder="New provider id" @keydown.enter.prevent="addProvider" />
        <button type="button" @click="addProvider">Add</button>
      </div>
    </aside>

    <section v-if="selectedProvider" class="provider-form">
      <div class="form-head">
        <label class="provider-id-field">
          <span>Provider ID</span>
          <input
            :value="editableProviderId"
            :class="{ invalid: providerIdError }"
            autocomplete="off"
            spellcheck="false"
            @input="setProviderId(($event.target as HTMLInputElement).value)"
            @blur="normalizeProviderId"
          />
          <small v-if="providerIdError" class="field-error">{{ providerIdError }}</small>
          <small v-else>Provider fields</small>
        </label>
        <div class="form-head-actions">
          <button
            type="button"
            class="oauth-button"
            :class="{ active: isOpenAIProvider && stringValue('authMode') === 'codex' }"
            :disabled="codexAuthBusy || !isOpenAIProvider"
            :title="isOpenAIProvider ? '切换当前 Provider 的 OpenAI OAuth 授权' : 'OAuth 仅支持 type 为 openai 的 Provider'"
            @click="setOfficialAuthEnabled(stringValue('authMode') !== 'codex')"
          >
            {{ stringValue('authMode') === 'codex' ? 'OAuth ✓' : 'OAuth' }}
          </button>
          <button type="button" @click="duplicateProvider">Duplicate</button>
          <button type="button" class="danger" @click="deleteProvider">Delete</button>
        </div>
      </div>

      <div v-if="limitWarning || activeLimitWarnings.length" class="limit-warning">
        <strong>ProviderLimit</strong>
        <span>{{ limitWarning || activeLimitWarnings[0] }}</span>
      </div>

      <div class="form-grid">
        <ProviderAuthFields
          :provider-type="stringValue('type')"
          :auth-mode="stringValue('authMode') || 'api_key'"
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
          @login="beginOfficialLogin"
        />
        <label>
          <span>Model</span>
          <select
            :value="stringValue('model')"
            :disabled="modelOptions.length === 0"
            @change="setField('model', ($event.target as HTMLSelectElement).value)"
          >
            <option value="">{{ modelOptions.length ? 'Unset' : 'No discovered models' }}</option>
            <option v-for="modelId in modelOptions" :key="modelId" :value="modelId">{{ modelId }}</option>
          </select>
        </label>
        <label>
          <span>Timeout Ms</span>
          <input :value="numberValue('timeoutMs')" type="number" min="1" @input="setNumberField('timeoutMs', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>Concurrency Limit</span>
          <input :value="numberValue('concurrencyLimit')" type="number" min="1" placeholder="Unlimited" @input="setNumberField('concurrencyLimit', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>RPM Limit</span>
          <input :value="numberValue('rpmLimit')" type="number" min="1" placeholder="Unlimited" @input="setNumberField('rpmLimit', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>TPM Limit (Input + Output)</span>
          <input :value="numberValue('tpmLimit')" type="number" min="1" placeholder="Unlimited" @input="setNumberField('tpmLimit', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>Max Tokens</span>
          <input :value="numberValue('maxTokens')" type="number" min="1" @input="setNumberField('maxTokens', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>Reasoning Effort</span>
          <select :value="stringValue('reasoningEffort')" @change="setField('reasoningEffort', ($event.target as HTMLSelectElement).value)">
            <option value="">Unset</option>
            <option value="minimal">minimal</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="xhigh">xhigh</option>
            <option value="max">max</option>
            <option value="auto">auto</option>
          </select>
        </label>
        <label>
          <span>Reasoning Summary</span>
          <select :value="stringValue('reasoningSummary')" @change="setField('reasoningSummary', ($event.target as HTMLSelectElement).value)">
            <option value="">Unset</option>
            <option value="auto">auto</option>
            <option value="concise">concise</option>
            <option value="detailed">detailed</option>
            <option value="disabled">disabled</option>
          </select>
        </label>
        <label>
          <span>Thinking</span>
          <select :value="stringValue('thinking')" @change="setField('thinking', ($event.target as HTMLSelectElement).value)">
            <option value="">Unset</option>
            <option value="enabled">enabled</option>
            <option value="disabled">disabled</option>
            <option value="auto">auto</option>
          </select>
        </label>
      </div>

      <DoubaoSpeechManagementPanel
        v-if="isDoubaoAudioProvider"
        :provider-id="selectedProviderId"
      />

      <div class="switch-grid">
        <label class="switch-field" title="Hide this provider from node configuration options for non-local clients."><span>Private</span><input type="checkbox" :checked="booleanValue('private')" @change="setField('private', ($event.target as HTMLInputElement).checked)" /></label>
        <label class="switch-field"><span>Responses API</span><input type="checkbox" :checked="booleanValue('responsesApi')" @change="setField('responsesApi', ($event.target as HTMLInputElement).checked)" /></label>
        <label v-if="isOpenAIProvider && booleanValue('responsesApi')" class="switch-field" title="Request the provider's priority service tier for faster Responses processing."><span>Fast mode</span><input type="checkbox" :checked="booleanValue('fastMode')" @change="setField('fastMode', ($event.target as HTMLInputElement).checked)" /></label>
        <label class="switch-field"><span>Replay reasoning items</span><input type="checkbox" :checked="booleanValue('responsesReplayReasoningItems')" @change="setField('responsesReplayReasoningItems', ($event.target as HTMLInputElement).checked)" /></label>
        <label class="switch-field"><span>Tool context compaction</span><input type="checkbox" :checked="booleanValue('toolContextCompactionEnabled')" @change="setField('toolContextCompactionEnabled', ($event.target as HTMLInputElement).checked)" /></label>
        <label class="switch-field"><span>Item-level streaming</span><input type="checkbox" :checked="booleanValue('responsesItemLevelStreaming')" @change="setField('responsesItemLevelStreaming', ($event.target as HTMLInputElement).checked)" /></label>
      </div>

      <div class="form-grid">
        <label class="dropdown-field">
          <span>Support Modes</span>
          <SupportModeMultiSelect
            :selected-values="listValue('supportmode')"
            @update:selected-values="setField('supportmode', $event)"
          />
        </label>
        <label>
          <span>Web Search Sources</span>
          <textarea :value="textList(selectedProvider.webSearchSources)" @input="setField('webSearchSources', parseTextList(($event.target as HTMLTextAreaElement).value))"></textarea>
        </label>
        <label>
          <span>Web Search Max Keyword</span>
          <input :value="numberValue('webSearchMaxKeyword')" type="number" min="1" @input="setNumberField('webSearchMaxKeyword', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>Web Search Limit</span>
          <input :value="numberValue('webSearchLimit')" type="number" min="1" @input="setNumberField('webSearchLimit', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>Compaction Every Tool Calls</span>
          <input :value="numberValue('toolContextCompactionEveryToolCalls')" type="number" min="0" @input="setNumberField('toolContextCompactionEveryToolCalls', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>Compaction Input Tokens</span>
          <input :value="numberValue('toolContextCompactionInputTokens')" type="number" min="0" @input="setNumberField('toolContextCompactionInputTokens', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>Compaction Output Tokens</span>
          <input :value="numberValue('toolContextCompactionOutputTokens')" type="number" min="0" @input="setNumberField('toolContextCompactionOutputTokens', ($event.target as HTMLInputElement).value)" />
        </label>
        <label>
          <span>Tool Result Max Chars</span>
          <input :value="numberValue('toolResultSubmissionMaxChars')" type="number" min="1" @input="setNumberField('toolResultSubmissionMaxChars', ($event.target as HTMLInputElement).value)" />
        </label>
      </div>
    </section>
  </div>
</template>

<style scoped src="./ModelProviderSettingsForm.css"></style>
