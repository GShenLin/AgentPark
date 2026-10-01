<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onBeforeUnmount, provide, ref } from 'vue'
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
  type ProviderLimitCopyRequest,
  type ProviderModelAdditionRequest,
  type SettingsDocument,
  type SettingsSectionInfo,
  type ThemePresetInfo,
} from '../settingsApi'
import { DEFAULT_SETTINGS_SECTIONS, SECTION_MESSAGE_KEYS, useSettingsSections } from './settings/settingsSections'
import { createSettingsPageNavigation, settingsNavigationKey, useCompactSettings } from './settings/settingsNavigation'
import SettingsMobileCatalog from './settings/SettingsMobileCatalog.vue'
import LanguageSwitcher from './LanguageSwitcher.vue'
import ActionButton from './ActionButton.vue'
import SelectionButton from './SelectionButton.vue'
import CompanionSettingsForm from './settings/CompanionSettingsForm.vue'
import AccessSettingsPanel from './settings/AccessSettingsPanel.vue'
import type { CompanionCapabilityOption } from './settings/CompanionCapabilitySelect.vue'
import DefaultSettingsForm from './settings/DefaultSettingsForm.vue'
import HarnessSettingsPanel from './settings/HarnessSettingsPanel.vue'
import KnowledgeSettingsPanel from './settings/KnowledgeSettingsPanel.vue'
import SkillsSettingsPanel from './settings/SkillsSettingsPanel.vue'
import GatewaySettingsPanel from './settings/GatewaySettingsPanel.vue'
import PeerNetworkPanel from './settings/PeerNetworkPanel.vue'
import NodeSyncSettingsPanel from './settings/NodeSyncSettingsPanel.vue'
import ModelProviderSettingsForm from './settings/ModelProviderSettingsForm.vue'
import PressureSettingsPanel from './settings/PressureSettingsPanel.vue'
import ProviderTestSettingsPanel from './settings/ProviderTestSettingsPanel.vue'
import RuntimeEventsSettingsForm from './settings/RuntimeEventsSettingsForm.vue'
import StaticSettingsPanel from './settings/StaticSettingsPanel.vue'
import SystemExitPanel from './settings/SystemExitPanel.vue'
import ThemeSettingsForm from './settings/ThemeSettingsForm.vue'
import { applyWorkspaceTheme } from '../theme'
import { t } from '../i18n'

const NodeProfilerEditor = defineAsyncComponent(() => import('./settings/NodeProfilerEditor.vue'))

const props = withDefaults(defineProps<{
  backLabel?: string
  showBackButton?: boolean
}>(), {
  backLabel: 'Back',
  showBackButton: true,
})

const compact = useCompactSettings()

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
const gatewayDirty = ref(false)
const pendingProviderLimitCopies = ref<ProviderLimitCopyRequest[]>([])
const pendingProviderModelAdditions = ref<ProviderModelAdditionRequest[]>([])
const providerLimitSourceIds = ref<Record<string, string>>({})
const modelProviderFormRevision = ref(0)
const backButtonLabel = computed(() => {
  if (props.backLabel === 'Back') return t('common.back')
  return props.backLabel
})

const displaySections = useSettingsSections(sections)

const currentSection = computed(() => {
  return displaySections.value.find((item) => item.id === activeSection.value) || null
})

const activeLabel = computed(() => {
  const messageKey = SECTION_MESSAGE_KEYS[activeSection.value]
  if (messageKey) return t(messageKey)
  return currentSection.value?.label || activeSection.value
})

const isProviderTest = computed(() => activeSection.value === 'provider-test')
const isAuthorization = computed(() => activeSection.value === 'authorization')
const isHarness = computed(() => activeSection.value === 'harness')
const isKnowledge = computed(() => activeSection.value === 'knowledge')
const isSkills = computed(() => activeSection.value === 'skills')
const isGateway = computed(() => activeSection.value === 'gateway')
const isPressure = computed(() => activeSection.value === 'pressure')
const isToolStats = computed(() => activeSection.value === 'tool-stats')
const isNodeProfilerEditor = computed(() => activeSection.value === 'node-profiler-editor')
const isExitSection = computed(() => activeSection.value === 'exit')
const isPeerNetwork = computed(() => activeSection.value === 'peer-network')
const isNodeSync = computed(() => activeSection.value === 'node-sync')
const isVirtualSection = computed(() => isSkills.value || isNodeSync.value || isKnowledge.value || isHarness.value || isPeerNetwork.value || isAuthorization.value || isGateway.value || isProviderTest.value || isPressure.value || isToolStats.value || isNodeProfilerEditor.value || isExitSection.value)
const dirty = computed(() => (
  !isVirtualSection.value
  && (
    editorContent.value !== String(loadedDocument.value?.content || '')
    || (
      activeSection.value === 'model-provider'
      && (pendingProviderLimitCopies.value.length > 0 || pendingProviderModelAdditions.value.length > 0)
    )
  )
))
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
  if (sectionId === 'skills' || sectionId === 'node-sync' || sectionId === 'knowledge' || sectionId === 'harness' || sectionId === 'peer-network' || sectionId === 'authorization' || sectionId === 'gateway' || sectionId === 'provider-test' || sectionId === 'pressure' || sectionId === 'tool-stats' || sectionId === 'anim-editor' || sectionId === 'node-profiler-editor' || sectionId === 'exit') {
    activeSection.value = sectionId
    loadedDocument.value = null
    editorContent.value = ''
    advancedMode.value = false
    error.value = ''
    status.value = ''
    nodeProfilerDirty.value = false
    gatewayDirty.value = false
    return
  }
  loading.value = true
  error.value = ''
  status.value = ''
  try {
    const document = await getSettingsSection(sectionId)
    activeSection.value = sectionId
    nodeProfilerDirty.value = false
    gatewayDirty.value = false
    loadedDocument.value = document
    editorContent.value = document.content
    if (sectionId === 'model-provider') {
      pendingProviderLimitCopies.value = []
      pendingProviderModelAdditions.value = []
      providerLimitSourceIds.value = {}
      modelProviderFormRevision.value += 1
    }
    syncThemePresetState(document)
    advancedMode.value = false
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    loading.value = false
  }
}

async function selectSection(sectionId: string) {
  if (loading.value || saving.value) return
  if (sectionId === activeSection.value) { sectionOpen.value = true; return }
  if (!confirmLeave()) return
  sectionOpen.value = true
  await loadSection(sectionId)
}

const { sectionOpen, detailBack, confirmLeave, handleBack } = createSettingsPageNavigation({
  compact,
  busy: computed(() => loading.value || saving.value),
  hasChanges: computed(() => dirty.value || nodeProfilerDirty.value || gatewayDirty.value),
  confirmDiscard: () => window.confirm(t(nodeProfilerDirty.value ? 'settings.discardNodeProfiler' : 'settings.unsavedConfirm')),
  exit: () => emit('back'),
})
provide(settingsNavigationKey, { compact, detailBack })

async function reloadSection() {
  if (confirmLeave()) await loadSection()
}

function beforeUnload(event: BeforeUnloadEvent) {
  if (!dirty.value && !nodeProfilerDirty.value && !gatewayDirty.value) return
  event.preventDefault()
  event.returnValue = ''
}
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))

function handleProviderDuplicated(sourceProviderId: string, targetProviderId: string) {
  const sourceId = providerLimitSourceIds.value[sourceProviderId] || sourceProviderId
  pendingProviderLimitCopies.value.push({
    source_provider_id: sourceId,
    target_provider_id: targetProviderId,
  })
  providerLimitSourceIds.value = {
    ...providerLimitSourceIds.value,
    [targetProviderId]: sourceId,
  }
}

function handleProviderIdChanged(previousProviderId: string, nextProviderId: string) {
  const sourceId = providerLimitSourceIds.value[previousProviderId] || previousProviderId
  pendingProviderLimitCopies.value = pendingProviderLimitCopies.value.map((copy) => (
    copy.target_provider_id === previousProviderId
      ? { ...copy, target_provider_id: nextProviderId }
      : copy
  ))
  pendingProviderModelAdditions.value = pendingProviderModelAdditions.value.map((addition) => (
    addition.provider_id === previousProviderId
      ? { ...addition, provider_id: nextProviderId }
      : addition
  ))
  const nextSourceIds = { ...providerLimitSourceIds.value }
  delete nextSourceIds[previousProviderId]
  nextSourceIds[nextProviderId] = sourceId
  providerLimitSourceIds.value = nextSourceIds
}

function handleProviderDeleted(providerId: string) {
  pendingProviderLimitCopies.value = pendingProviderLimitCopies.value.filter(
    (copy) => copy.target_provider_id !== providerId,
  )
  pendingProviderModelAdditions.value = pendingProviderModelAdditions.value.filter(
    (addition) => addition.provider_id !== providerId,
  )
  const nextSourceIds = { ...providerLimitSourceIds.value }
  delete nextSourceIds[providerId]
  providerLimitSourceIds.value = nextSourceIds
}

function handleProviderModelAdded(providerId: string, modelId: string) {
  if (pendingProviderModelAdditions.value.some(
    (addition) => addition.provider_id === providerId && addition.model_id === modelId,
  )) return
  pendingProviderModelAdditions.value.push({ provider_id: providerId, model_id: modelId })
}

function providerLimitCopiesForSave() {
  const dataProviders = formData.value?.providers
  if (!dataProviders || typeof dataProviders !== 'object' || Array.isArray(dataProviders)) return []
  return pendingProviderLimitCopies.value.filter(
    (copy) => Object.prototype.hasOwnProperty.call(dataProviders, copy.target_provider_id),
  )
}

function providerModelAdditionsForSave() {
  const dataProviders = formData.value?.providers
  if (!dataProviders || typeof dataProviders !== 'object' || Array.isArray(dataProviders)) return []
  return pendingProviderModelAdditions.value.filter(
    (addition) => Object.prototype.hasOwnProperty.call(dataProviders, addition.provider_id),
  )
}

defineExpose({ requestBack: handleBack })

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
    const document = await updateSettingsSection(
      activeSection.value,
      editorContent.value,
      activeSection.value === 'model-provider' ? providerLimitCopiesForSave() : [],
      activeSection.value === 'model-provider' ? providerModelAdditionsForSave() : [],
    )
    loadedDocument.value = document
    editorContent.value = document.content
    if (activeSection.value === 'model-provider') {
      pendingProviderLimitCopies.value = []
      pendingProviderModelAdditions.value = []
      providerLimitSourceIds.value = {}
    }
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
  <section class="settings-page" :class="{ 'settings-compact': compact, 'section-open': sectionOpen }">
    <header class="settings-head">
      <div class="settings-title-wrap">
        <h1>{{ compact && sectionOpen ? activeLabel : t('common.settings') }}</h1>
        <div class="settings-path">{{ loadedDocument?.path || currentSection?.path || (isAuthorization ? '.auth/access-control.json' : isGateway ? 'config/publicGateway.json · .auth/gateway/keys.json' : isProviderTest ? 'config/ProviderLimit.json' : isPressure ? '/api/providers/pressure' : isToolStats ? 'memories/*/runtime_events.jsonl · messages.jsonl · .cache/tool_stats' : isNodeProfilerEditor ? 'agent/*.json' : isExitSection ? 'AgentPark backend' : '') }}</div>
      </div>
      <div v-if="props.showBackButton || compact" class="settings-head-actions">
        <ActionButton compact :disabled="loading || saving" @click="handleBack">‹ {{ backButtonLabel }}</ActionButton>
      </div>
      <LanguageSwitcher v-if="compact" compact />
    </header>

    <div v-if="loading" class="settings-loading" role="status">{{ t('common.loading') }}</div>
    <div v-if="error && compact && !sectionOpen" class="settings-error" role="alert">{{ error }}</div>
    <div class="settings-body">
      <SettingsMobileCatalog v-if="compact" v-show="!sectionOpen" :sections="displaySections" :active="activeSection" :disabled="loading || saving" @select="selectSection" />
      <nav v-else class="settings-tabs" :aria-label="t('settings.sectionsAria')">
        <SelectionButton
          v-for="section in displaySections"
          :key="section.id"
          class="settings-tab"
          :active="activeSection === section.id"
          :disabled="loading || saving"
          @click="selectSection(section.id)"
        >
          {{ labelFor(section) }}
        </SelectionButton>
      </nav>

      <main v-show="!compact || sectionOpen" class="settings-editor" :inert="loading || saving" :aria-busy="loading || saving">
        <div v-if="!isGateway && (!isVirtualSection || !compact)" class="editor-toolbar">
          <div class="editor-title">
            <span>{{ activeLabel }}</span>
            <span v-if="dirty" class="editor-state">{{ t('settings.unsaved') }}</span>
            <span v-else-if="status" class="editor-state saved">{{ status }}</span>
          </div>
          <div class="editor-actions">
            <ActionButton v-if="!isVirtualSection" compact :disabled="loading || saving" @click="reloadSection">{{ t('settings.reload') }}</ActionButton>
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
        <HarnessSettingsPanel v-else-if="isHarness" />
        <KnowledgeSettingsPanel v-else-if="isKnowledge" />
        <SkillsSettingsPanel v-else-if="isSkills" />
        <GatewaySettingsPanel v-else-if="isGateway" @dirty="gatewayDirty = $event" />
        <PeerNetworkPanel v-else-if="isPeerNetwork" />
        <NodeSyncSettingsPanel v-else-if="isNodeSync" />
        <ProviderTestSettingsPanel v-else-if="isProviderTest" />
        <PressureSettingsPanel v-else-if="isPressure" />
        <StaticSettingsPanel v-else-if="isToolStats" />
        <NodeProfilerEditor
          v-else-if="isNodeProfilerEditor"
          :providers="providers"
          :available-tools="availableTools"
          @error="error = $event"
          @status="status = $event"
          @dirty="nodeProfilerDirty = $event"
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
            :key="modelProviderFormRevision"
            :data="formData"
            @update:data="replaceData"
            @provider-duplicated="handleProviderDuplicated"
            @provider-id-changed="handleProviderIdChanged"
            @provider-deleted="handleProviderDeleted"
            @provider-model-added="handleProviderModelAdded"
          />
          <DefaultSettingsForm
            v-else-if="activeSection === 'defaults' && formData"
            :data="formData"
            :memory-defaults="loadedDocument?.long_term_memory_defaults"
            :conversation-defaults="loadedDocument?.conversation_context_defaults"
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

        <div v-if="error" class="settings-error" role="alert">{{ error }}</div>
      </main>
    </div>
  </section>
</template>

<style scoped src="./settings/SettingsPage.css"></style>
<style scoped src="./settings/SettingsMobile.css"></style>

