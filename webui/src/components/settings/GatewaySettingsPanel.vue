<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createGatewayKey,
  deleteGatewayKey,
  deleteGatewayModel,
  getGatewaySettings,
  testGateway,
  updateGatewayOptions,
  upsertGatewayModel,
  type GatewayModel,
  type GatewayProtocol,
  type GatewaySettings,
} from '../../settingsApi'

const settings = ref<GatewaySettings | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const status = ref('')
const createdKey = ref('')
const keyName = ref('')
const customKey = ref('')
const modelId = ref('')
const providerId = ref('')
const accountId = ref('')
const modelEnabled = ref(true)
const protocols = ref<GatewayProtocol[]>(['responses', 'chat_completions', 'messages'])
const testModel = ref('')
const testProtocol = ref<GatewayProtocol>('responses')
const testPrompt = ref('Reply with exactly: AgentPark gateway ready.')
const testResult = ref('')

const protocolOptions: Array<{ id: GatewayProtocol; label: string }> = [
  { id: 'responses', label: 'Responses' },
  { id: 'chat_completions', label: 'Chat Completions' },
  { id: 'messages', label: 'Messages' },
]

const selectedProvider = computed(() => (
  settings.value?.providers.find((item) => item.id === providerId.value) || null
))
const selectedModel = computed(() => (
  settings.value?.models.find((item) => item.id === testModel.value) || null
))
const availableTestProtocols = computed(() => selectedModel.value?.protocols || [])
const endpointBase = computed(() => `${window.location.origin}/v1`)

async function load() {
  loading.value = true
  error.value = ''
  try {
    settings.value = await getGatewaySettings()
    if (!providerId.value) providerId.value = settings.value.providers[0]?.id || ''
    if (!testModel.value || !settings.value.models.some((item) => item.id === testModel.value)) {
      testModel.value = settings.value.models[0]?.id || ''
    }
    syncTestProtocol()
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    loading.value = false
  }
}

async function saveOptions() {
  if (!settings.value) return
  saving.value = true
  error.value = ''
  try {
    settings.value = await updateGatewayOptions({
      enabled: settings.value.enabled,
      requireApiKey: settings.value.requireApiKey,
    })
    status.value = 'Gateway options saved'
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}

function toggleProtocol(protocol: GatewayProtocol, checked: boolean) {
  protocols.value = checked
    ? Array.from(new Set([...protocols.value, protocol]))
    : protocols.value.filter((item) => item !== protocol)
}

async function saveModel() {
  if (!modelId.value.trim() || !providerId.value || !protocols.value.length) {
    error.value = 'Public model id, Provider, and at least one protocol are required.'
    return
  }
  saving.value = true
  error.value = ''
  try {
    settings.value = await upsertGatewayModel({
      id: modelId.value.trim(),
      providerId: providerId.value,
      accountId: accountId.value,
      protocols: protocols.value,
      enabled: modelEnabled.value,
    })
    status.value = `Model ${modelId.value.trim()} saved`
    resetModelForm()
    if (!testModel.value) testModel.value = settings.value.models[0]?.id || ''
    syncTestProtocol()
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}

function editModel(model: GatewayModel) {
  modelId.value = model.id
  providerId.value = model.providerId
  accountId.value = model.accountId
  protocols.value = [...model.protocols]
  modelEnabled.value = model.enabled
}

function resetModelForm() {
  modelId.value = ''
  accountId.value = ''
  protocols.value = ['responses', 'chat_completions', 'messages']
  modelEnabled.value = true
}

async function removeModel(id: string) {
  if (!window.confirm(`Delete public model "${id}"?`)) return
  saving.value = true
  error.value = ''
  try {
    settings.value = await deleteGatewayModel(id)
    status.value = `Model ${id} deleted`
    if (testModel.value === id) testModel.value = settings.value.models[0]?.id || ''
    syncTestProtocol()
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}

async function addKey() {
  if (!keyName.value.trim()) {
    error.value = 'Key name is required.'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const response = await createGatewayKey({
      name: keyName.value.trim(),
      ...(customKey.value.trim() ? { key: customKey.value.trim() } : {}),
    })
    if (settings.value) settings.value.keys = response.keys
    createdKey.value = response.created.key
    keyName.value = ''
    customKey.value = ''
    status.value = 'Endpoint Key created'
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}

async function removeKey(id: string, name: string) {
  if (!window.confirm(`Delete Endpoint Key "${name}"? Clients using it will stop working.`)) return
  saving.value = true
  error.value = ''
  try {
    const response = await deleteGatewayKey(id)
    if (settings.value) settings.value.keys = response.keys
    status.value = `Endpoint Key ${name} deleted`
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}

async function copyCreatedKey() {
  if (!createdKey.value) return
  await navigator.clipboard.writeText(createdKey.value)
  status.value = 'Endpoint Key copied'
}

function syncTestProtocol() {
  const available = availableTestProtocols.value
  if (available.length && !available.includes(testProtocol.value)) {
    testProtocol.value = available[0]!
  }
}

async function runTest() {
  if (!testModel.value) {
    error.value = 'Create and select a public model first.'
    return
  }
  saving.value = true
  error.value = ''
  testResult.value = ''
  try {
    const response = await testGateway({
      model: testModel.value,
      protocol: testProtocol.value,
      prompt: testPrompt.value,
    })
    testResult.value = JSON.stringify(response.response, null, 2)
    status.value = `Gateway test returned HTTP ${response.status}`
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="gateway-panel">
    <section class="gateway-card">
      <div class="card-head">
        <div>
          <h2>Public Gateway</h2>
          <p>AgentPark exposes OpenAI Responses, Chat Completions, and Anthropic Messages on the same server.</p>
        </div>
        <button type="button" :disabled="loading || saving" @click="load">Reload</button>
      </div>
      <div class="endpoint-row">
        <code>{{ endpointBase }}</code>
        <span>Models: /models · Responses: /responses · Chat: /chat/completions · Messages: /messages</span>
      </div>
      <div v-if="settings" class="option-row">
        <label><input v-model="settings.enabled" type="checkbox"> Enable Public Gateway</label>
        <label><input v-model="settings.requireApiKey" type="checkbox"> Require Endpoint Key</label>
        <button type="button" class="primary" :disabled="saving" @click="saveOptions">Save options</button>
      </div>
    </section>

    <section class="gateway-card">
      <div class="card-head">
        <div>
          <h2>Public models</h2>
          <p>A public model id maps to one AgentPark Provider and, optionally, one explicit OAuth/API-key account.</p>
        </div>
      </div>
      <div class="model-form">
        <label>
          Public model id
          <input v-model="modelId" placeholder="agentpark-codex">
        </label>
        <label>
          Provider
          <select v-model="providerId" @change="accountId = ''">
            <option v-for="provider in settings?.providers || []" :key="provider.id" :value="provider.id">
              {{ provider.id }} · {{ provider.model }}
            </option>
          </select>
        </label>
        <label>
          Fixed account
          <select v-model="accountId">
            <option value="">Provider default / configured account</option>
            <option v-for="account in selectedProvider?.accounts || []" :key="account.id" :value="account.id">
              {{ account.alias || account.identity || account.id }} · {{ account.id }}
            </option>
          </select>
        </label>
        <div class="protocol-field">
          <span>Protocols</span>
          <label v-for="option in protocolOptions" :key="option.id">
            <input
              type="checkbox"
              :checked="protocols.includes(option.id)"
              @change="toggleProtocol(option.id, ($event.target as HTMLInputElement).checked)"
            >
            {{ option.label }}
          </label>
        </div>
        <label class="enabled-field"><input v-model="modelEnabled" type="checkbox"> Enabled</label>
        <div class="form-actions">
          <button type="button" class="primary" :disabled="saving" @click="saveModel">Save model</button>
          <button type="button" :disabled="saving" @click="resetModelForm">Clear</button>
        </div>
      </div>
      <div class="item-list">
        <article v-for="model in settings?.models || []" :key="model.id" class="item-row">
          <div>
            <strong>{{ model.id }}</strong>
            <span>{{ model.providerId }} · {{ model.accountId || 'Provider default account' }}</span>
            <small>{{ model.protocols.join(', ') }} · {{ model.enabled ? 'Enabled' : 'Disabled' }}</small>
          </div>
          <div class="row-actions">
            <button type="button" @click="editModel(model)">Edit</button>
            <button type="button" class="danger" @click="removeModel(model.id)">Delete</button>
          </div>
        </article>
        <p v-if="settings && !settings.models.length" class="empty">No public model mappings yet.</p>
      </div>
    </section>

    <section class="gateway-card">
      <div class="card-head">
        <div>
          <h2>Endpoint Keys</h2>
          <p>Keys authorize only /v1 endpoints. Settings and other LAN APIs remain unchanged.</p>
        </div>
      </div>
      <div class="key-form">
        <label>Key name <input v-model="keyName" placeholder="Laptop / App name"></label>
        <label>Custom value (optional) <input v-model="customKey" autocomplete="off" placeholder="Leave blank to generate"></label>
        <button type="button" class="primary" :disabled="saving" @click="addKey">Add Key</button>
      </div>
      <div v-if="createdKey" class="created-key">
        <strong>Copy this key now. It is shown only once.</strong>
        <code>{{ createdKey }}</code>
        <button type="button" @click="copyCreatedKey">Copy</button>
      </div>
      <div class="item-list">
        <article v-for="key in settings?.keys || []" :key="key.id" class="item-row">
          <div>
            <strong>{{ key.name }}</strong>
            <span>{{ key.prefix }}</span>
            <small>{{ new Date(key.createdAt).toLocaleString() }}</small>
          </div>
          <button type="button" class="danger" @click="removeKey(key.id, key.name)">Delete</button>
        </article>
        <p v-if="settings && !settings.keys.length" class="empty">No Endpoint Keys yet.</p>
      </div>
    </section>

    <section class="gateway-card">
      <div class="card-head">
        <div>
          <h2>Public Endpoint Test</h2>
          <p>Runs through the same model mapping and shared protocol engine as /v1.</p>
        </div>
      </div>
      <div class="test-form">
        <select v-model="testModel" @change="syncTestProtocol">
          <option v-for="model in settings?.models || []" :key="model.id" :value="model.id">{{ model.id }}</option>
        </select>
        <select v-model="testProtocol">
          <option v-for="protocol in availableTestProtocols" :key="protocol" :value="protocol">
            {{ protocolOptions.find((item) => item.id === protocol)?.label || protocol }}
          </option>
        </select>
        <input v-model="testPrompt" placeholder="Test prompt">
        <button type="button" class="primary" :disabled="saving || !testModel" @click="runTest">Test</button>
      </div>
      <pre v-if="testResult" class="test-result">{{ testResult }}</pre>
    </section>

    <div v-if="status" class="notice success">{{ status }}</div>
    <div v-if="error" class="notice error">{{ error }}</div>
  </div>
</template>

<style scoped src="./GatewaySettingsPanel.css"></style>
