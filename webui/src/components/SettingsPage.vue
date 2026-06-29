<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getNodeTemplate, listProviders, listTools, type ProviderInfo } from '../api'
import { getSchemaFieldOptions } from '../composables/nodeSchemaFields'
import {
  getSettingsSection,
  listSettingsSections,
  updateSettingsSection,
  type SettingsDocument,
  type SettingsSectionInfo,
} from '../settingsApi'
import CompanionSettingsForm from './settings/CompanionSettingsForm.vue'
import type { CompanionCapabilityOption } from './settings/CompanionCapabilitySelect.vue'
import DefaultSettingsForm from './settings/DefaultSettingsForm.vue'
import ModuleProviderSettingsForm from './settings/ModuleProviderSettingsForm.vue'
import ProviderTestSettingsPanel from './settings/ProviderTestSettingsPanel.vue'

const props = withDefaults(defineProps<{
  backLabel?: string
}>(), {
  backLabel: 'Board',
})

const emit = defineEmits<{
  back: []
  providersUpdated: []
}>()

const sections = ref<SettingsSectionInfo[]>([])
const activeSection = ref('module-provider')
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
  return base
})

const currentSection = computed(() => {
  return sections.value.find((item) => item.id === activeSection.value) || null
})

const activeLabel = computed(() => {
  if (activeSection.value === 'module-provider') return 'moduleProvider'
  if (activeSection.value === 'defaults') return 'Default settings'
  if (activeSection.value === 'companion') return 'Companion'
  if (activeSection.value === 'provider-test') return 'Test'
  return currentSection.value?.label || activeSection.value
})

const isProviderTest = computed(() => activeSection.value === 'provider-test')
const dirty = computed(() => !isProviderTest.value && editorContent.value !== String(loadedDocument.value?.content || ''))

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
  if (section.id === 'provider-test') return 'Test'
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
  sections.value = await listSettingsSections()
  if (!displaySections.value.some((item) => item.id === activeSection.value)) {
    activeSection.value = sections.value[0]?.id || 'module-provider'
  }
}

async function loadSection(sectionId = activeSection.value) {
  if (sectionId === 'provider-test') {
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
    const document = await updateSettingsSection(activeSection.value, editorContent.value)
    loadedDocument.value = document
    editorContent.value = document.content
    status.value = 'Saved'
    if (activeSection.value === 'module-provider') {
      emit('providersUpdated')
      await loadCatalogForForms()
    } else if (activeSection.value === 'defaults') {
      await loadCompanionCapabilityOptions()
    }
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
        <div class="settings-path">{{ loadedDocument?.path || currentSection?.path || (isProviderTest ? 'config/ProviderLimit.json' : '') }}</div>
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
            <button v-if="!isProviderTest" type="button" class="settings-btn" :disabled="loading || saving" @click="loadSection()">Reload</button>
            <button v-if="!isProviderTest" type="button" class="settings-btn" :disabled="loading || saving" @click="advancedMode = !advancedMode">
              {{ advancedMode ? 'Form' : 'Advanced JSON' }}
            </button>
            <button v-if="!isProviderTest && advancedMode" type="button" class="settings-btn" :disabled="loading || saving" @click="formatJson">Format</button>
            <button v-if="!isProviderTest" type="button" class="settings-btn primary" :disabled="loading || saving || !dirty" @click="saveSection">
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
          </div>
        </div>

        <ProviderTestSettingsPanel v-if="isProviderTest" />

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
          <div v-else class="settings-error">Invalid JSON. Switch to Advanced JSON to fix it.</div>
        </template>

        <div v-if="error" class="settings-error">{{ error }}</div>
      </main>
    </div>
  </section>
</template>

<style scoped src="./settings/SettingsPage.css"></style>

