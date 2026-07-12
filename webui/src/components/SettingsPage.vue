<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import {
  applyRuntimeEventConfig,
  getNodeTemplate,
  listAgentProfiles,
  listProviders,
  listTools,
  type AgentProfile,
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
import CompanionSettingsForm from './settings/CompanionSettingsForm.vue'
import type { CompanionCapabilityOption } from './settings/CompanionCapabilitySelect.vue'
import DefaultSettingsForm from './settings/DefaultSettingsForm.vue'
import ModuleProviderSettingsForm from './settings/ModuleProviderSettingsForm.vue'
import PressureSettingsPanel from './settings/PressureSettingsPanel.vue'
import ProviderTestSettingsPanel from './settings/ProviderTestSettingsPanel.vue'
import RuntimeEventsSettingsForm from './settings/RuntimeEventsSettingsForm.vue'
import SystemExitPanel from './settings/SystemExitPanel.vue'
import ThemeSettingsForm from './settings/ThemeSettingsForm.vue'
import ToolStatsSettingsPanel from './settings/ToolStatsSettingsPanel.vue'
import { applyWorkspaceTheme } from '../theme'

const AnimEditor = defineAsyncComponent(() => import('./settings/AnimEditor.vue'))
const DEFAULT_SETTINGS_SECTIONS: SettingsSectionInfo[] = [
  {
    id: 'module-provider',
    label: 'moduleProvider',
    path: 'config/moduleProvider.json',
    filename: 'moduleProvider.json',
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
}>()

const sections = ref<SettingsSectionInfo[]>(DEFAULT_SETTINGS_SECTIONS.slice())
const activeSection = ref('module-provider')
const loadedDocument = ref<SettingsDocument | null>(null)
const editorContent = ref('')
const advancedMode = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const status = ref('')
const providers = ref<ProviderInfo[]>([])
const agentProfiles = ref<AgentProfile[]>([])
const availableTools = ref<string[]>([])
const companionCapabilityOptions = ref<Record<string, CompanionCapabilityOption[]>>({})
const themePresets = ref<ThemePresetInfo[]>([])
const activeThemePresetId = ref('default')

const displaySections = computed<SettingsSectionInfo[]>(() => {
  const base = sections.value.slice()
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
      path: 'config/moduleProvider.json',
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
  if (activeSection.value === 'module-provider') return 'moduleProvider'
  if (activeSection.value === 'defaults') return 'Default settings'
  if (activeSection.value === 'companion') return 'Companion'
  if (activeSection.value === 'events') return 'Runtime Events'
  if (activeSection.value === 'provider-test') return 'Test'
  if (activeSection.value === 'pressure') return 'Pressure'
  if (activeSection.value === 'tool-stats') return 'Static'
  if (activeSection.value === 'anim-editor') return 'AnimEditor'
  if (activeSection.value === 'exit') return 'Exit'
  return currentSection.value?.label || activeSection.value
})

const isProviderTest = computed(() => activeSection.value === 'provider-test')
const isPressure = computed(() => activeSection.value === 'pressure')
const isToolStats = computed(() => activeSection.value === 'tool-stats')
const isAnimEditor = computed(() => activeSection.value === 'anim-editor')
const isExitSection = computed(() => activeSection.value === 'exit')
const isVirtualSection = computed(() => isProviderTest.value || isPressure.value || isToolStats.value || isAnimEditor.value || isExitSection.value)
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
  if (section.id === 'module-provider') return 'moduleProvider'
  if (section.id === 'defaults') return 'Default settings'
  if (section.id === 'companion') return 'Companion'
  if (section.id === 'events') return 'Runtime Events'
  if (section.id === 'provider-test') return 'Test'
  if (section.id === 'pressure') return 'Pressure'
  if (section.id === 'tool-stats') return 'Static'
  if (section.id === 'anim-editor') return 'AnimEditor'
  if (section.id === 'exit') return 'Exit'
  return section.label
}

function replaceData(data: Record<string, unknown>) {
  editorContent.value = `${JSON.stringify(data, null, 2)}\n`
  status.value = ''
  error.value = ''
}

async function loadCatalog() {
  const [nextProviders, nextTools, nextAgentProfiles] = await Promise.all([
    listProviders(),
    listTools(),
    listAgentProfiles(),
  ])
  providers.value = nextProviders
  availableTools.value = nextTools
  agentProfiles.value = nextAgentProfiles
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
    activeSection.value = sections.value[0]?.id || 'module-provider'
  }
}

async function loadSection(sectionId = activeSection.value) {
  if (sectionId === 'provider-test' || sectionId === 'pressure' || sectionId === 'tool-stats' || sectionId === 'anim-editor' || sectionId === 'exit') {
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
  await loadSection(sectionId)
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
      status.value = 'Applied'
      return
    }
    const document = await updateSettingsSection(activeSection.value, editorContent.value)
    loadedDocument.value = document
    editorContent.value = document.content
    syncThemePresetState(document)
    status.value = 'Saved'
    if (activeSection.value === 'module-provider') {
      emit('providersUpdated')
      await loadCatalogForForms()
    } else if (activeSection.value === 'defaults') {
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
    status.value = `Loaded ${safeId}`
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}

async function handleSaveThemePreset(presetId: string) {
  const safeId = String(presetId || '').trim()
  if (!safeId) {
    error.value = 'Theme preset id is required.'
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
    status.value = `Saved ${safeId}`
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
        <h1>Settings</h1>
        <div class="settings-path">{{ loadedDocument?.path || currentSection?.path || (isProviderTest ? 'config/ProviderLimit.json' : isPressure ? '/api/providers/pressure' : isToolStats ? '.cache/tool_stats' : isAnimEditor ? 'petAvatars/*/frame.json' : isExitSection ? 'AgentPark backend' : '') }}</div>
      </div>
      <div class="settings-head-actions">
        <button type="button" class="settings-btn" @click="emit('back')">{{ props.backLabel }}</button>
      </div>
    </header>

    <div class="settings-body">
      <nav class="settings-tabs" aria-label="Settings sections">
        <button
          v-for="section in displaySections"
          :key="section.id"
          type="button"
          class="settings-tab"
          :class="{ active: activeSection === section.id }"
          @click="selectSection(section.id)"
        >
          {{ labelFor(section) }}
        </button>
      </nav>

      <main class="settings-editor">
        <div class="editor-toolbar">
          <div class="editor-title">
            <span>{{ activeLabel }}</span>
            <span v-if="dirty" class="editor-state">Unsaved</span>
            <span v-else-if="status" class="editor-state saved">{{ status }}</span>
          </div>
          <div class="editor-actions">
            <button v-if="!isVirtualSection" type="button" class="settings-btn" :disabled="loading || saving" @click="loadSection()">Reload</button>
            <button v-if="!isVirtualSection" type="button" class="settings-btn" :disabled="loading || saving" @click="advancedMode = !advancedMode">
              {{ advancedMode ? 'Form' : 'Advanced JSON' }}
            </button>
            <button v-if="!isVirtualSection && advancedMode" type="button" class="settings-btn" :disabled="loading || saving" @click="formatJson">Format</button>
            <button v-if="!isVirtualSection" type="button" class="settings-btn primary" :disabled="loading || saving || (activeSection !== 'events' && !dirty)" @click="saveSection">
              {{ saving ? (activeSection === 'events' ? 'Applying...' : 'Saving...') : (activeSection === 'events' ? 'Apply' : 'Save') }}
            </button>
          </div>
        </div>

        <div v-if="validationWarnings.length" class="settings-warning" role="status">
          <strong>Configuration warning</strong>
          <span v-for="warning in validationWarnings" :key="warning">{{ warning }}</span>
        </div>

        <ProviderTestSettingsPanel v-if="isProviderTest" />
        <PressureSettingsPanel v-else-if="isPressure" />
        <ToolStatsSettingsPanel v-else-if="isToolStats" />
        <AnimEditor v-else-if="isAnimEditor" @error="error = $event" @status="status = $event" />
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
          <ModuleProviderSettingsForm
            v-if="activeSection === 'module-provider' && formData"
            :data="formData"
            @update:data="replaceData"
          />
          <DefaultSettingsForm
            v-else-if="activeSection === 'defaults' && formData"
            :data="formData"
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
            :agent-profiles="agentProfiles"
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
          <div v-else class="settings-error">Invalid JSON. Switch to Advanced JSON to fix it.</div>
        </template>

        <div v-if="error" class="settings-error">{{ error }}</div>
      </main>
    </div>
  </section>
</template>

<style scoped src="./settings/SettingsPage.css"></style>

