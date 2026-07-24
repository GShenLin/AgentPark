<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { deleteAgentProfile, getNodeTemplate, listAgentProfiles, type AgentProfile, type NodeInfo } from '../../api'
import { useAgentNodeCreateSchema } from '../../composables/useAgentNodeCreateSchema'
import { useProviderDrivenTemplateSchema } from '../../composables/useProviderDrivenTemplateSchema'
import { useGlobalState } from '../../composables/useGlobalState'
import { normalizeSchemaFieldValue } from '../../composables/nodeSchemaFields'
import { AgentBoardKey } from './context'
import AgentProfileDropdown from './AgentProfileDropdown.vue'
import NodeConfigFields from './NodeConfigFields.vue'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected
const { providers, availableTools } = useGlobalState()

const menuEl = ref<HTMLElement | null>(null)
const searchInputRef = ref<HTMLInputElement | null>(null)

const showMenu = ref(false)
const menuQuery = ref('')
const menuLeft = ref(0)
const menuTop = ref(0)
const createPoint = ref({ x: 0, y: 0 })

const nodeDialogLoading = ref(false)
const creatingNode = ref(false)
const showNodeDialog = ref(false)
const selectedTypeId = ref('')
const selectedNodeName = ref('')
const selectedNodeSchema = ref<Record<string, any>>({})
const selectedNodeFields = ref<Record<string, any>>({})
const agentProfiles = ref<AgentProfile[]>([])
const profileLoading = ref(false)
const deletingProfileId = ref('')
const {
  toolOptions,
  createProviderOptions,
  ensureCreateAgentSelections,
} = useAgentNodeCreateSchema({
  selectedTypeId,
  selectedNodeFields,
  providers,
  availableTools,
})
const { loading: providerSchemaLoading } = useProviderDrivenTemplateSchema({
  typeId: selectedTypeId,
  fields: selectedNodeFields,
  schema: selectedNodeSchema,
  onError: (error) => { ctx.lastError.value = String((error as { message?: unknown })?.message || error || '') },
})

const sortedNodes = computed(() => {
  return [...ctx.availableNodes.value]
    .sort((a, b) => {
    const left = String(a.name || a.id)
    const right = String(b.name || b.id)
    return left.localeCompare(right)
  })
})

const filteredNodes = computed(() => {
  const query = String(menuQuery.value || '').trim().toLowerCase()
  if (!query) return sortedNodes.value
  return sortedNodes.value.filter((node) => {
    const name = String(node.name || '').toLowerCase()
    const id = String(node.id || '').toLowerCase()
    const description = String(node.description || '').toLowerCase()
    return name.includes(query) || id.includes(query) || description.includes(query)
  })
})

const schemaKeys = computed(() => Object.keys(selectedNodeSchema.value || {}))

function closeMenu() {
  showMenu.value = false
  menuQuery.value = ''
}

function closeDialog() {
  showNodeDialog.value = false
}

function onWindowKeyDown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  if (showNodeDialog.value) {
    closeDialog()
    return
  }
  if (showMenu.value) {
    closeMenu()
  }
}

function updateMenuPosition() {
  const menu = menuEl.value
  if (!menu) return
  const width = menu.offsetWidth || 320
  const height = menu.offsetHeight || 360
  const margin = 12
  const maxLeft = Math.max(margin, window.innerWidth - width - margin)
  const maxTop = Math.max(margin, window.innerHeight - height - margin)
  menuLeft.value = Math.max(margin, Math.min(menuLeft.value, maxLeft))
  menuTop.value = Math.max(margin, Math.min(menuTop.value, maxTop))
}

async function refreshAgentProfiles() {
  profileLoading.value = true
  try {
    agentProfiles.value = await listAgentProfiles()
  } catch (e: any) {
    ctx.lastError.value = String(e?.message || e)
  } finally {
    profileLoading.value = false
  }
}

async function openNodeTemplate(node: NodeInfo) {
  nodeDialogLoading.value = true
  ctx.lastError.value = null
  try {
    const tpl = await getNodeTemplate(node.id)
    const schema = (tpl.schema || {}) as Record<string, any>
    const fields = { ...(tpl.fields || {}) }
    const hasConfigFields = Object.keys(schema).length > 0
    if (!hasConfigFields) {
      await ctx.createNodeAtPosition(node.id, String(tpl.name || node.name || node.id), createPoint.value, fields)
      closeMenu()
      return
    }
    selectedTypeId.value = node.id
    selectedNodeName.value = String(tpl.name || node.name || node.id)
    selectedNodeSchema.value = schema
    selectedNodeFields.value = fields
    ensureCreateAgentSelections()
    showNodeDialog.value = true
    closeMenu()
  } catch (e: any) {
    ctx.lastError.value = String(e?.message || e)
  } finally {
    nodeDialogLoading.value = false
  }
}

function openAt(screenPoint: { x: number; y: number }, boardPoint: { x: number; y: number }) {
  createPoint.value = {
    x: Number(boardPoint?.x ?? 0),
    y: Number(boardPoint?.y ?? 0),
  }
  menuLeft.value = Number(screenPoint?.x ?? 0)
  menuTop.value = Number(screenPoint?.y ?? 0)
  showMenu.value = true
  menuQuery.value = ''
  void refreshAgentProfiles()
  void nextTick(() => {
    updateMenuPosition()
    searchInputRef.value?.focus()
    searchInputRef.value?.select()
  })
}

async function createFromProfile(profileId: string) {
  const safeProfileId = String(profileId || '').trim()
  if (!safeProfileId) return
  const profile = agentProfiles.value.find((item) => item.id === safeProfileId)
  if (!profile) return
  ctx.lastError.value = null
  try {
    await ctx.createNodeAtPosition(
      profile.node_type_id,
      String(profile.node_name || profile.name || profile.id),
      createPoint.value,
      { ...(profile.fields || {}) },
    )
    closeMenu()
  } catch (e: any) {
    ctx.lastError.value = String(e?.message || e)
  }
}

async function deleteProfile(profileId: string) {
  const safeProfileId = String(profileId || '').trim()
  if (!safeProfileId || deletingProfileId.value) return
  const profile = agentProfiles.value.find((item) => item.id === safeProfileId)
  const profileName = String(profile?.name || profile?.id || safeProfileId)
  if (!window.confirm(`Delete profile "${profileName}"?`)) return
  deletingProfileId.value = safeProfileId
  ctx.lastError.value = null
  try {
    await deleteAgentProfile(safeProfileId)
    await refreshAgentProfiles()
    window.dispatchEvent(new CustomEvent('agent-profiles-changed'))
  } catch (e: any) {
    ctx.lastError.value = String(e?.message || e)
  } finally {
    deletingProfileId.value = ''
  }
}

function setSelectedNodeField(key: string, value: any) {
  selectedNodeFields.value = { ...selectedNodeFields.value, [key]: value }
}

function showFieldError(message: string) {
  ctx.lastError.value = String(message || '').trim() || null
}

async function confirmCreateNode() {
  if (!selectedTypeId.value) return
  creatingNode.value = true
  ctx.lastError.value = null
  try {
    const fields: Record<string, unknown> = {}
    for (const key of schemaKeys.value) {
      fields[key] = normalizeSchemaFieldValue(selectedNodeSchema.value, key, selectedNodeFields.value[key])
    }
    await ctx.createNodeAtPosition(selectedTypeId.value, selectedNodeName.value, createPoint.value, fields)
    showNodeDialog.value = false
  } catch (e: any) {
    ctx.lastError.value = String(e?.message || e)
  } finally {
    creatingNode.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', onWindowKeyDown)
  window.addEventListener('resize', updateMenuPosition)
  window.addEventListener('agent-profiles-changed', refreshAgentProfiles)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeyDown)
  window.removeEventListener('resize', updateMenuPosition)
  window.removeEventListener('agent-profiles-changed', refreshAgentProfiles)
})

watch(
  () => [
    selectedTypeId.value,
    createProviderOptions.value.join('|'),
    toolOptions.value.join('|'),
  ],
  () => {
    ensureCreateAgentSelections()
  },
)

defineExpose({
  openAt,
  closeMenu,
})
</script>

<template>
  <Teleport to="body">
    <div v-if="showMenu" class="context-menu-overlay" @pointerdown="closeMenu" @contextmenu.prevent="closeMenu">
      <section
        ref="menuEl"
        class="context-menu"
        :style="{ left: `${menuLeft}px`, top: `${menuTop}px` }"
        @pointerdown.stop
        @contextmenu.prevent
      >
        <header class="context-menu-head">
          <div class="context-menu-title-row">
            <div class="context-menu-title">Create Node</div>
            <AgentProfileDropdown
              :profiles="agentProfiles"
              :loading="profileLoading"
              :deleting-profile-id="deletingProfileId"
              @select="createFromProfile"
              @delete="deleteProfile"
            />
          </div>
          <div class="context-menu-sub">Right-click position: {{ Math.round(createPoint.x) }}, {{ Math.round(createPoint.y) }}</div>
        </header>

        <input
          ref="searchInputRef"
          v-model="menuQuery"
          class="context-menu-search"
          type="text"
          placeholder="Search node name or type"
          @pointerdown.stop
        />

        <div class="context-menu-list">
          <button
            v-for="node in filteredNodes"
            :key="node.id"
            class="context-menu-item"
            :disabled="nodeDialogLoading"
            @click="openNodeTemplate(node)"
          >
            <div class="context-menu-item-name">{{ node.name || node.id }}</div>
            <div class="context-menu-item-id">{{ node.id }}</div>
            <div v-if="node.description" class="context-menu-item-desc">{{ node.description }}</div>
          </button>

          <div v-if="filteredNodes.length === 0" class="context-menu-empty">No matching nodes.</div>
        </div>
      </section>
    </div>

    <div v-if="showNodeDialog" class="modal-overlay" @click.self="closeDialog">
      <div class="modal">
        <h3>Create Node</h3>

        <label class="field">
          <span class="field-label">Node Name</span>
          <input v-model="selectedNodeName" class="field-input" type="text" />
        </label>

        <NodeConfigFields
          :type-id="selectedTypeId"
          :schema="selectedNodeSchema"
          :fields="selectedNodeFields"
          :providers="providers"
          :available-tools="availableTools"
          @update-field="setSelectedNodeField"
          @field-error="showFieldError"
        />

        <div class="modal-actions">
          <button @click="closeDialog">Cancel</button>
          <button class="primary" :disabled="creatingNode || providerSchemaLoading" @click="confirmCreateNode">
            {{ creatingNode ? 'Creating...' : 'Create Node' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.context-menu-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
}

.context-menu {
  position: fixed;
  width: min(360px, calc(100vw - 24px));
  max-height: min(520px, calc(100vh - 24px));
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid var(--theme-panel-canvas-context-menu-button-border, rgba(148, 163, 184, 0.2));
  background-color: var(--theme-panel-canvas-context-menu-background-color, rgba(2, 6, 23, 0.96));
  background-image: var(--theme-panel-canvas-context-menu-background-image, none);
  background-size: var(--theme-panel-canvas-context-menu-background-size, cover);
  background-position: var(--theme-panel-canvas-context-menu-background-position, center);
  background-repeat: var(--theme-panel-canvas-context-menu-background-repeat, no-repeat);
  background-blend-mode: var(--theme-panel-canvas-context-menu-background-blend-mode, normal);
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
}

.context-menu-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.context-menu-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.context-menu-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 700;
  color: var(--theme-panel-canvas-context-menu-button-text, rgba(248, 250, 252, 0.96));
}

.context-menu-sub {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.82);
}

.context-menu-search,
.field-input {
  width: 100%;
  border: 1px solid var(--theme-panel-canvas-context-menu-button-border, rgba(148, 163, 184, 0.3));
  border-radius: 8px;
  background: var(--theme-panel-canvas-context-menu-button-background, rgba(15, 23, 42, 0.72));
  color: var(--theme-panel-canvas-context-menu-button-text, rgba(226, 232, 240, 0.96));
  padding: 8px 10px;
  font-size: 12px;
  outline: none;
}

.context-menu-search:focus,
.field-input:focus {
  border-color: rgba(56, 189, 248, 0.7);
}

.context-menu-list {
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-right: 2px;
}

.context-menu-item {
  width: 100%;
  text-align: left;
  border-radius: 10px;
  border: 1px solid var(--theme-panel-canvas-context-menu-button-border, rgba(148, 163, 184, 0.22));
  background: var(--theme-panel-canvas-context-menu-button-background, rgba(15, 23, 42, 0.7));
  color: var(--theme-panel-canvas-context-menu-button-text, rgba(226, 232, 240, 0.95));
  padding: 9px 10px;
}

.context-menu-item:hover:not(:disabled) {
  border-color: rgba(56, 189, 248, 0.6);
  background: var(--theme-panel-canvas-context-menu-button-hover-background, rgba(14, 116, 144, 0.2));
}

.context-menu-item:disabled {
  opacity: 0.6;
  cursor: wait;
}

.context-menu-item-name {
  font-size: 12px;
  font-weight: 700;
}

.context-menu-item-id,
.context-menu-item-desc,
.context-menu-empty,
.field-label {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.88);
}

.context-menu-item-id,
.context-menu-item-desc {
  margin-top: 2px;
  word-break: break-all;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.55);
  z-index: 1200;
}

.modal {
  width: min(520px, calc(100vw - 32px));
  max-height: calc(100vh - 48px);
  overflow: auto;
  background: #1e293b;
  padding: 24px;
  border-radius: 12px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.42);
}

.modal h3 {
  margin: 0 0 16px;
  color: #fff;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}

.field-check {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.field-textarea {
  min-height: 78px;
  resize: vertical;
  line-height: 1.4;
}

.field-hint {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.78);
  line-height: 1.35;
}

.field-checkbox {
  width: 16px;
  height: 16px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.modal-actions button.primary {
  background: rgba(99, 102, 241, 0.4);
  border: 1px solid rgba(99, 102, 241, 0.72);
}
</style>
