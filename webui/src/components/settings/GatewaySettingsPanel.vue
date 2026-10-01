<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  createGatewayKey,
  deleteGatewayKey,
  testGateway,
  type GatewayProtocol,
} from '../../gatewayApi'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import FormCheckbox from '../FormCheckbox.vue'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'
import { t } from '../../i18n'
import GatewayUsagePanel from './GatewayUsagePanel.vue'
import GatewayModelsEditor from './GatewayModelsEditor.vue'
import { gatewayProtocolOptions as protocolOptions } from './gatewayModelEditor'
import { useGatewaySettingsEditor } from './gatewaySettingsEditor'

const editor = useGatewaySettingsEditor()
const { settings, enabled, requireApiKey, models, dirty, loading, error, status, discard } = editor
const emit = defineEmits<{ dirty: [value: boolean] }>()
watch(dirty, value => emit('dirty', value), { immediate: true })
const actionBusy = ref(false)
const saving = computed(() => editor.saving.value || actionBusy.value)
const createdKey = ref('')
const keyName = ref('')
const customKey = ref('')
const testModel = ref('')
const testProtocol = ref<GatewayProtocol>('responses')
const testPrompt = ref('Reply with exactly: AgentPark gateway ready.')
const testResult = ref('')
const testImageUrl = ref('')
const testImages = ref<string[]>([])

const selectedModel = computed(() => (
  settings.value?.models.find((item) => item.id === testModel.value) || null
))
const enabledModels = computed(() => settings.value?.models.filter((model) => model.enabled) || [])
const availableTestProtocols = computed(() => selectedModel.value?.protocols || [])
const endpointBase = computed(() => `${window.location.origin}/v1`)
function syncSavedModels() {
  if (!enabledModels.value.some((model) => model.id === testModel.value)) {
    testModel.value = enabledModels.value[0]?.id || ''
  }
  testResult.value = ''
  testImages.value = []
  syncTestProtocol()
}

async function load() {
  await editor.load()
  syncSavedModels()
}

async function saveSettings() {
  if (await editor.save()) syncSavedModels()
}

async function addKey() {
  if (!keyName.value.trim()) {
    error.value = 'Key name is required.'
    return
  }
  actionBusy.value = true
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
    actionBusy.value = false
  }
}

async function removeKey(id: string, name: string) {
  if (!window.confirm(`Delete Endpoint Key "${name}"? Clients using it will stop working.`)) return
  actionBusy.value = true
  error.value = ''
  try {
    const response = await deleteGatewayKey(id)
    if (settings.value) settings.value.keys = response.keys
    status.value = `Endpoint Key ${name} deleted`
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    actionBusy.value = false
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
  actionBusy.value = true
  error.value = ''
  testResult.value = ''
  testImages.value = []
  try {
    const response = await testGateway({
      model: testModel.value,
      protocol: testProtocol.value,
      prompt: testPrompt.value,
      ...(testProtocol.value === 'images_edits' ? { images: [{ image_url: testImageUrl.value }] } : {}),
    })
    const body = response.response
    if (testProtocol.value.startsWith('images_') && Array.isArray(body.data)) {
      testImages.value = body.data.flatMap((item: Record<string, unknown>) => typeof item.b64_json === 'string'
        ? [`data:image/${body.output_format || 'png'};base64,${item.b64_json}`] : typeof item.url === 'string' ? [item.url] : [])
      testResult.value = JSON.stringify({ ...body, data: body.data.map((item: Record<string, unknown>) => ({ ...item, ...(item.b64_json ? { b64_json: '[shown below]' } : {}) })) }, null, 2)
    } else testResult.value = JSON.stringify(body, null, 2)
    status.value = `Gateway test returned HTTP ${response.status}`
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    actionBusy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="gateway-page">
    <header class="gateway-toolbar">
      <div class="gateway-toolbar-title">
        <strong>{{ t('settings.gateway') }}</strong>
        <span v-if="dirty" class="gateway-dirty">{{ t('settings.unsaved') }}</span>
      </div>
      <div class="gateway-toolbar-actions">
        <ActionButton compact :disabled="loading || saving || !dirty" @click="discard">{{ t('gateway.discardModels') }}</ActionButton>
        <ActionButton variant="primary" compact :disabled="loading || saving || !settings || !dirty" @click="saveSettings">
          {{ saving ? t('common.saving') : t('gateway.saveOptions') }}
        </ActionButton>
      </div>
      <div v-if="error" class="gateway-feedback error" role="alert">{{ error }}</div>
      <div v-else-if="status && !dirty" class="gateway-feedback success" role="status">{{ status }}</div>
    </header>
    <div class="gateway-panel">
      <section class="gateway-card">
        <div class="card-head">
          <div>
            <h2>{{ t('gateway.public') }}</h2>
            <p>{{ t('gateway.description') }}</p>
          </div>
          <ActionButton compact :disabled="loading || saving || dirty" @click="load">{{ t('settings.reload') }}</ActionButton>
        </div>
        <div class="endpoint-row">
          <code>{{ endpointBase }}</code>
          <span>/models · /responses · /chat/completions · /messages · /images/generations · /images/edits (JSON)</span>
        </div>
        <div v-if="settings" class="option-row">
          <label><FormCheckbox v-model="enabled" :disabled="loading || saving" /> {{ t('gateway.enable') }}</label>
          <label><FormCheckbox v-model="requireApiKey" :disabled="loading || saving" /> {{ t('gateway.requireKey') }}</label>
        </div>
        <div v-for="sourceError in settings?.sourceErrors || []" :key="sourceError.id" class="notice error">
          {{ sourceError.id }} unavailable: {{ sourceError.error }}
        </div>
      </section>

      <GatewayModelsEditor
        v-if="settings"
        :editor="models"
        :providers="settings.providers"
        :disabled="loading || saving"
      />

      <section class="gateway-card">
        <div class="card-head">
          <div>
            <h2>{{ t('gateway.keys') }}</h2>
            <p>{{ t('gateway.keysHelp') }}</p>
          </div>
        </div>
        <div class="key-form">
          <label>{{ t('gateway.keyName') }} <FormTextInput v-model="keyName" :placeholder="t('gateway.keyNamePlaceholder')" /></label>
          <label>{{ t('gateway.customValue') }} <FormTextInput v-model="customKey" autocomplete="off" :placeholder="t('gateway.generatePlaceholder')" /></label>
          <ActionButton variant="primary" compact :disabled="saving" @click="addKey">{{ t('gateway.addKey') }}</ActionButton>
        </div>
        <div v-if="createdKey" class="created-key">
          <strong>{{ t('gateway.copyNow') }}</strong>
          <code>{{ createdKey }}</code>
          <ActionButton compact @click="copyCreatedKey">{{ t('gateway.copy') }}</ActionButton>
        </div>
        <div class="item-list">
          <article v-for="key in settings?.keys || []" :key="key.id" class="item-row">
            <div>
              <strong>{{ key.name }}</strong>
              <span>{{ key.prefix }}</span>
              <small>{{ new Date(key.createdAt).toLocaleString() }}</small>
            </div>
            <DangerButton :disabled="saving" @click="removeKey(key.id, key.name)">{{ t('common.delete') }}</DangerButton>
          </article>
          <p v-if="settings && !settings.keys.length" class="empty">{{ t('gateway.emptyKeys') }}</p>
        </div>
      </section>

      <section class="gateway-card">
        <div class="card-head">
          <div>
            <h2>{{ t('gateway.testTitle') }}</h2>
            <p>{{ t('gateway.testHelp') }}</p>
          </div>
        </div>
        <div class="test-form">
          <FormSelect v-model="testModel" @change="syncTestProtocol">
            <option v-for="model in enabledModels" :key="model.id" :value="model.id">{{ model.id }}</option>
          </FormSelect>
          <FormSelect v-model="testProtocol">
            <option v-for="protocol in availableTestProtocols" :key="protocol" :value="protocol">
              {{ protocolOptions.find((item) => item.id === protocol)?.label || protocol }}
            </option>
          </FormSelect>
          <FormTextInput v-model="testPrompt" :placeholder="t('gateway.testPrompt')" />
          <FormTextInput v-if="testProtocol === 'images_edits'" v-model="testImageUrl" placeholder="Reference image URL or data URL" />
          <ActionButton variant="primary" compact :disabled="saving || !testModel" @click="runTest">{{ t('common.test') }}</ActionButton>
        </div>
        <pre v-if="testResult" class="test-result">{{ testResult }}</pre>
        <img v-for="(image, index) in testImages" :key="index" :src="image" alt="Gateway test image" style="max-width: 100%; max-height: 480px" />
      </section>

      <GatewayUsagePanel />

    </div>
  </div>
</template>

<style scoped src="./GatewaySettingsPanel.css"></style>
