<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import {
  applyRuntimeEventConfig,
  getNodeTemplate,
  listProviders,
  listTools,
  type ProviderInfo,
} from '../api'
import { getSchemaFieldOptions } from '../composables/nodeSchemaFields'
import { formatRuntimeApplyErrors } from '../runtimeEventsConfig'
import {
  getSettingsSection,
  listThemePresets,
  loadThemePreset,
  listSettingsSections,
  saveThemePreset,
  updateSettingsSection,
  type SettingsDocument,
  type SettingsSectionInfo,
  type ThemePresetInfo,
} from '../settingsApi'
import ActionButton from './ActionButton.vue'
import SelectionButton from './SelectionButton.vue'
import CompanionSettingsForm from './settings/CompanionSettingsForm.vue'
import AccessSettingsPanel from './settings/AccessSettingsPanel.vue'
import type { CompanionCapabilityOption } from './settings/CompanionCapabilitySelect.vue'
import DefaultSettingsForm from './settings/DefaultSettingsForm.vue'
import GatewaySettingsPanel from './settings/GatewaySettingsPanel.vue'
import ModelProviderSettingsForm from './settings/ModelProviderSettingsForm.vue'
import PressureSettingsPanel from './settings/PressureSettingsPanel.vue'
import ProviderTestSettingsPanel from './settings/ProviderTestSettingsPanel.vue'
import RuntimePolicySettingsPanel from './settings/RuntimePolicySettingsPanel.vue'
import RuntimeEventsSettingsForm from './settings/RuntimeEventsSettingsForm.vue'
import StaticSettingsPanel from './settings/StaticSettingsPanel.vue'
import SystemExitPanel from './settings/SystemExitPanel.vue'
import ThemeSettingsForm from './settings/ThemeSettingsForm.vue'
import { applyWorkspaceTheme } from '../theme'
import { t } from '../i18n'

const AnimEditor = defineAsyncComponent(() => import('./settings/AnimEditor.vue'))
const NodeProfilerEditor = defineAsyncComponent(() => import('./settings/NodeProfilerEditor.vue'))
const DEFAULT_SETTINGS_SECTIONS: SettingsSectionInfo[] = [
  {
    id: 'model-provider',
    label: 'modelProvider',
    path: 'config/modelProvider.json',
    filename: 'modelProvider.json',
  },
  {
    id: 'defaults',
    label: 'Default settings',
    path: 'config/config.json',
    filename: 'config.json',
  },
  {
    id: 'companion',
    label: 'Companion',
    path: 'memories/companion/config.json',
    filename: 'config.json',
  },
  {
    id: 'events',
    label: 'Runtime Events',
    path: 'config/events.json',
    filename: 'events.json',
  },
]

const props = withDefaults(defineProps<{
  backLabel?: string
}>(), {
  backLabel: 'Board',
})

const emit = defineEmits<{
  back: []
  providersUpdated: []
  defaultsUpdated: [value: Record<string, unknown>]
}>()

const sections = ref<SettingsSectionInfo[]>(DEFAULT_SETTINGS_SECTIONS.slice())
const activeSection = ref('model-provider')
const loadedDocument = ref<SettingsDocument | null>(null)
const editorContent = ref('')
const advancedMode = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const status = ref('')
const providers = ref<ProviderInfo[]>([])
const availableTools = ref<string[]>([])
const companionCapabilityOptions = ref<Record<string, CompanionCapabilityOption[]>>({})
const themePresets = ref<ThemePresetInfo[]>([])
const activeThemePresetId = ref('default')
const nodeProfilerDirty = ref(false)
const runtimePolicyDirty = ref(false)
const backButtonLabel = computed(() => {
  if (props.backLabel === 'Board') return t('common.board')
  if (props.backLabel === 'Back') return t('common.back')
  return props.backLabel
})

const SECTION_MESSAGE_KEYS: Record<string, string> = {
  authorization: 'settings.authorization',
  'model-provider': 'settings.modelProvider',
  gateway: 'settings.gateway',
  defaults: 'settings.defaults',
  companion: 'settings.companion',
  events: 'settings.runtimeEvents',
  'provider-test': 'settings.providerTest',
  pressure: 'settings.pressure',
  'tool-stats': 'settings.statistics',
  'anim-editor': 'settings.animationEditor',
  'node-profiler-editor': 'settings.nodeProfiler',
  'runtime-policy': 'settings.runtimePolicy',
  exit: 'settings.exit',
  theme: 'settings.theme',
}

const displaySections = computed<SettingsSectionInfo[]>(() => {
  const base = sections.value.slice()
  if (!base.some((item) => item.id === 'authorization')) {
    base.unshift({
      id: 'authorization',
      label: 'Authorization',
      path: '.auth/access-control.json',
      filename: 'access-control.json',
    })
  }
  if (!base.some((item) => item.id === 'gateway')) {
    base.splice(Math.min(1, base.length), 0, {
      id: 'gateway',
      label: 'Gateway',
      path: 'config/publicGateway.json · .auth/gateway/keys.json',
      filename: 'publicGateway.json',
    })
  }
  if (!base.some((item) => item.id === 'provider-test')) {
    base.push({
      id: 'provider-test',
      label: 'Test',
      path: 'config/ProviderLimit.json',
      filename: 'ProviderLimit.json',
    })
  }
  if (!base.some((item) => item.id === 'pressure')) {
    base.push({
      id: 'pressure',
      label: 'Pressure',
      path: 'config/modelProvider.json',
      filename: '',
    })
  }
  if (!base.some((item) => item.id === 'tool-stats')) {
    base.push({
      id: 'tool-stats',
      label: 'Static',
      path: '.cache/tool_stats',
      filename: 'summary.json',
    })
  }
  if (!base.some((item) => item.id === 'anim-editor')) {
    base.push({
      id: 'anim-editor',
      label: 'AnimEditor',
      path: 'petAvatars',
      filename: 'frame.json',
    })
  }
  if (!base.some((item) => item.id === 'node-profiler-editor')) {
    base.push({
      id: 'node-profiler-editor',
      label: 'NodeProfilerEditor',
      path: 'agent/*.json',
      filename: '*.json',
    })
  }
  if (!base.some((item) => item.id === 'runtime-policy')) {
    base.push({
      id: 'runtime-policy',
      label: 'RuntimePolicy',
      path: 'config/runtimePolicies.json · config/runtime_policies/*.json',
      filename: 'runtimePolicies.json',
    })
  }
  if (!base.some((item) => item.id === 'exit')) {
    base.push({
      id: 'exit',
      label: 'Exit',
      path: 'AgentPark backend',
      filename: '',
    })
  }
  return base
})

const currentSection = computed(() => {
  return sections.value.find((item) => item.id === activeSection.value) || null
})

const activeLabel = computed(() => {
  const messageKey = SECTION_MESSAGE_KEYS[activeSection.value]
  if (messageKey) return t(messageKey)
  return currentSection.value?.label || activeSection.value
})

const isProviderTest = computed(() => activeSection.value === 'provider-test')
const isAuthorization = computed(() => activeSection.value === 'authorization')
const isGateway = computed(() => activeSection.value === 'gateway')
const isPressure = computed(() => activeSection.value === 'pressure')
const isToolStats = computed(() => activeSection.value === 'tool-stats')
const isAnimEditor = computed(() => activeSection.value === 'anim-editor')
const isNodeProfilerEditor = computed(() => activeSection.value === 'node-profiler-editor')
const isRuntimePolicy = computed(() => activeSection.value === 'runtime-policy')
const isExitSection = computed(() => activeSection.value === 'exit')
const isVirtualSection = computed(() => isAuthorization.value || isGateway.value || isProviderTest.value || isPressure.value || isToolStats.value || isAnimEditor.value || isNodeProfilerEditor.value || isRuntimePolicy.value || isExitSection.value)
const dirty = computed(() => !isVirtualSection.value && editorContent.value !== String(loadedDocument.value?.content || ''))
const validationWarnings = computed(() => Array.isArray(loadedDocument.value?.warnings)
  ? loadedDocument.value.warnings.map((item) => String(item || '').trim()).filter(Boolean)
  : [])

const formData = computed<Record<string, unknown> | null>(() => {
  try {
    const parsed = JSON.parse(editorContent.value || '{}')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null
  } catch {
    return null
  }
})

function labelFor(section: SettingsSectionInfo) {
  const messageKey = SECTION_MESSAGE_KEYS[section.id]
  if (messageKey) return t(messageKey)
  return section.label
}

function replaceData(data: Record<string, unknown>) {
  editorContent.value = `${JSON.stringify(data, null, 2)}\n`
  status.value = ''
  error.value = ''
}

async function loadCatalog() {
  const [nextProviders, nextTools] = await Promise.all([
    listProviders(),
    listTools(),
  ])
  providers.value = nextProviders
  availableTools.value = nextTools
}

function syncThemePresetState(document: SettingsDocument | null) {
  if (!document || document.section !== 'theme') return
  activeThemePresetId.value = String(document.active_preset_id || activeThemePresetId.value || 'default')
  themePresets.value = Array.isArray(document.presets) ? document.presets : themePresets.value
}

async function loadCatalogForForms() {
  try {
    await loadCatalog()
    await loadCompanionCapabilityOptions()
  } catch (e: any) {
    error.value = String(e?.message || e)
  }
}

async function loadCompanionCapabilityOptions() {
  const template = await getNodeTemplate('agent_node')
  const schema = template.schema || {}
  companionCapabilityOptions.value = {
    tools: getSchemaFieldOptions(schema, 'tools'),
    mcp_servers: getSchemaFieldOptions(schema, 'mcp_servers'),
    skills: getSchemaFieldOptions(schema, 'skills'),
    plugins: getSchemaFieldOptions(schema, 'plugins'),
  }
}

async function loadSections() {
  const nextSections = await listSettingsSections()
  sections.value = nextSections.length ? nextSections : DEFAULT_SETTINGS_SECTIONS.slice()
  if (!displaySections.value.some((item) => item.id === activeSection.value)) {
    activeSection.value = sections.value[0]?.id || 'model-provider'
  }
}

async function loadSection(sectionId = activeSection.value) {
  if (sectionId === 'authorization' || sectionId === 'gateway' || sectionId === 'provider-test' || sectionId === 'pressure' || sectionId === 'tool-stats' || sectionId === 'anim-editor' || sectionId === 'node-profiler-editor' || sectionId === 'runtime-policy' || sectionId === 'exit') {
    activeSection.value = sectionId
    loadedDocument.value = null
    editorContent.value = ''
    advancedMode.value = false
    error.value = ''
    status.value = ''
    return
  }
  loading.value = true
  error.value = ''
  status.value = ''
  try {
    activeSection.value = sectionId
    const document = await getSettingsSection(sectionId)
    loadedDocument.value = document
    editorContent.value = document.content
    syncThemePresetState(document)
    advancedMode.value = false
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    loading.value = false
  }
}

async function selectSection(sectionId: string) {
  if (sectionId === activeSection.value) return
  if (isNodeProfilerEditor.value && nodeProfilerDirty.value && !window.confirm(t('settings.discardNodeProfiler'))) {
    return
  }
  if (isRuntimePolicy.value && runtimePolicyDirty.value && !window.confirm(t('settings.discardRuntimePolicy'))) {
    return
  }
  nodeProfilerDirty.value = false
  runtimePolicyDirty.value = false
  await loadSection(sectionId)
}

function handleBack() {
  if (isNodeProfilerEditor.value && nodeProfilerDirty.value && !window.confirm(t('settings.discardNodeProfiler'))) {
    return
  }
  if (isRuntimePolicy.value && runtimePolicyDirty.value && !window.confirm(t('settings.discardRuntimePolicy'))) {
    return
  }
  emit('back')
}

function formatJson() {
  error.value = ''
  status.value = ''
  try {
    const parsed = JSON.parse(editorContent.value)
    editorContent.value = `${JSON.stringify(parsed, null, 2)}\n`
  } catch (e: any) {
    error.value = String(e?.message || e)
  }
}

async function saveSection() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  status.value = ''
  try {
    if (activeSection.value === 'events') {
      const parsed = JSON.parse(editorContent.value || '{}')
      const result = await applyRuntimeEventConfig(parsed)
      if (!result.ok) {
        throw new Error(formatRuntimeApplyErrors(result.errors))
      }
      editorContent.value = `${JSON.stringify(parsed, null, 2)}\n`
      loadedDocument.value = {
        section: 'events',
        label: 'Runtime Events',
        path: loadedDocument.value?.path || 'config/events.json',
        content: editorContent.value,
        data: parsed,
      }
      status.value = t('settings.applied')
      return
    }
    const document = await updateSettingsSection(activeSection.value, editorContent.value)
    loadedDocument.value = document
    editorContent.value = document.content
    syncThemePresetState(document)
    status.value = document.restart_required ? t('settings.restartRequired') : t('common.saved')
    if (activeSection.value === 'model-provider') {
      emit('providersUpdated')
      await loadCatalogForForms()
    } else if (activeSection.value === 'defaults') {
      emit('defaultsUpdated', document.data)
      await loadCompanionCapabilityOptions()
    } else if (activeSection.value === 'theme') {
      await applyWorkspaceTheme()
    }
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}

async function refreshThemePresets() {
  const catalog = await listThemePresets()
  activeThemePresetId.value = String(catalog.active_preset_id || 'default')
  themePresets.value = Array.isArray(catalog.presets) ? catalog.presets : []
}

async function handleLoadThemePreset(presetId: string) {
  const safeId = String(presetId || '').trim()
  if (!safeId) return
  saving.value = true
  error.value = ''
  status.value = ''
  try {
    const document = await loadThemePreset(safeId)
    loadedDocument.value = document
    editorContent.value = document.content
    syncThemePresetState(document)
    await applyWorkspaceTheme()
    status.value = t('settings.loadedPreset', { preset: safeId })
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}

async function handleSaveThemePreset(presetId: string) {
  const safeId = String(presetId || '').trim()
  if (!safeId) {
    error.value = t('settings.themePresetRequired')
    return
  }
  saving.value = true
  error.value = ''
  status.value = ''
  try {
    const document = await saveThemePreset(safeId, editorContent.value)
    loadedDocument.value = document
    editorContent.value = document.content
    syncThemePresetState(document)
    await applyWorkspaceTheme()
    status.value = t('settings.savedPreset', { preset: safeId })
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    await loadSections()
    await loadSection(activeSection.value)
    await loadCatalogForForms()
  } catch (e: any) {
    error.value = String(e?.message || e)
  }
})
</script>

<template>
  <section class="settings-page">
    <header class="settings-head">
      <div class="settings-title-wrap">
        <h1>{{ t('common.settings') }}</h1>
        <div class="settings-path">{{ loadedDocument?.path || currentSection?.path || (isAuthorization ? '.auth/access-control.json' : isGateway ? 'config/publicGateway.json · .auth/gateway/keys.json' : isProviderTest ? 'config/ProviderLimit.json' : isPressure ? '/api/providers/pressure' : isToolStats ? 'memories/*/runtime_events.jsonl · messages.jsonl · .cache/tool_stats' : isAnimEditor ? 'petAvatars/*/frame.json' : isNodeProfilerEditor ? 'agent/*.json' : isRuntimePolicy ? 'config/runtimePolicies.json · config/runtime_policies/*.json' : isExitSection ? 'AgentPark backend' : '') }}</div>
      </div>
      <div class="settings-head-actions">
        <ActionButton compact @click="handleBack">{{ backButtonLabel }}</ActionButton>
      </div>
    </header>

    <div class="settings-body">
      <nav class="settings-tabs" :aria-label="t('settings.sectionsAria')">
        <SelectionButton
          v-for="section in displaySections"
          :key="section.id"
          class="settings-tab"
          :active="activeSection === section.id"
          @click="selectSection(section.id)"
        >
          {{ labelFor(section) }}
        </SelectionButton>
      </nav>

      <main class="settings-editor">
        <div class="editor-toolbar">
          <div class="editor-title">
            <span>{{ activeLabel }}</span>
            <span v-if="dirty" class="editor-state">{{ t('settings.unsaved') }}</span>
            <span v-else-if="status" class="editor-state saved">{{ status }}</span>
          </div>
          <div class="editor-actions">
            <ActionButton v-if="!isVirtualSection" compact :disabled="loading || saving" @click="loadSection()">{{ t('settings.reload') }}</ActionButton>
            <ActionButton v-if="!isVirtualSection" compact :disabled="loading || saving" @click="advancedMode = !advancedMode">
              {{ advancedMode ? t('settings.form') : t('settings.advancedJson') }}
            </ActionButton>
            <ActionButton v-if="!isVirtualSection && advancedMode" compact :disabled="loading || saving" @click="formatJson">{{ t('settings.format') }}</ActionButton>
            <ActionButton v-if="!isVirtualSection" variant="primary" compact :disabled="loading || saving || (activeSection !== 'events' && !dirty)" @click="saveSection">
              {{ saving ? (activeSection === 'events' ? t('settings.applying') : t('common.saving')) : (activeSection === 'events' ? t('settings.apply') : t('common.save')) }}
            </ActionButton>
          </div>
        </div>

        <div v-if="validationWarnings.length" class="settings-warning" role="status">
          <strong>{{ t('settings.configurationWarning') }}</strong>
          <span v-for="warning in validationWarnings" :key="warning">{{ warning }}</span>
        </div>

        <AccessSettingsPanel v-if="isAuthorization" />
        <GatewaySettingsPanel v-else-if="isGateway" />
        <ProviderTestSettingsPanel v-else-if="isProviderTest" />
        <PressureSettingsPanel v-else-if="isPressure" />
        <StaticSettingsPanel v-else-if="isToolStats" />
        <AnimEditor v-else-if="isAnimEditor" @error="error = $event" @status="status = $event" />
        <NodeProfilerEditor
          v-else-if="isNodeProfilerEditor"
          :providers="providers"
          :available-tools="availableTools"
          @error="error = $event"
          @status="status = $event"
          @dirty="nodeProfilerDirty = $event"
        />
        <RuntimePolicySettingsPanel
          v-else-if="isRuntimePolicy"
          @error="error = $event"
          @status="status = $event"
          @dirty="runtimePolicyDirty = $event"
        />
        <SystemExitPanel v-else-if="isExitSection" />

        <textarea
          v-else-if="advancedMode"
          v-model="editorContent"
          class="json-editor"
          spellcheck="false"
          :disabled="loading || saving"
          :aria-label="`${activeLabel} JSON`"
        ></textarea>

        <template v-else>
          <ModelProviderSettingsForm
            v-if="activeSection === 'model-provider' && formData"
            :data="formData"
            @update:data="replaceData"
          />
          <DefaultSettingsForm
            v-else-if="activeSection === 'defaults' && formData"
            :data="formData"
            :runtime="loadedDocument?.runtime"
            @update:data="replaceData"
          />
          <CompanionSettingsForm
            v-else-if="activeSection === 'companion' && formData"
            :data="formData"
            :providers="providers"
            :available-tools="availableTools"
            :capability-options="companionCapabilityOptions"
            @update:data="replaceData"
          />
          <RuntimeEventsSettingsForm
            v-else-if="activeSection === 'events' && formData"
            :data="formData"
            @update:data="replaceData"
          />
          <ThemeSettingsForm
            v-else-if="activeSection === 'theme' && formData"
            :data="formData"
            :presets="themePresets"
            :active-preset-id="activeThemePresetId"
            @update:data="replaceData"
            @load-preset="handleLoadThemePreset"
            @save-preset="handleSaveThemePreset"
            @refresh-presets="refreshThemePresets"
          />
          <div v-else class="settings-error">{{ t('settings.invalidJsonHelp') }}</div>
        </template>

        <div v-if="error" class="settings-error">{{ error }}</div>
      </main>
    </div>
  </section>
</template>

<style scoped src="./settings/SettingsPage.css"></style>

