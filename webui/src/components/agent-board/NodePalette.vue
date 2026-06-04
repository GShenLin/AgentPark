<script setup lang="ts">
import { inject, ref, watch } from 'vue'
import { getNodeTemplate } from '../../api'
import { AgentBoardKey, type AgentBoardContext } from './context'
import { useGlobalState } from '../../composables/useGlobalState'
import { useAgentNodeCreateSchema } from '../../composables/useAgentNodeCreateSchema'
import { normalizeSchemaFieldValue } from '../../composables/nodeSchemaFields'
import NodeConfigFields from './NodeConfigFields.vue'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx: AgentBoardContext = injected

const { lastError, providers, availableTools } = useGlobalState()

const showNodeDialog = ref(false)
const nodeDialogLoading = ref(false)
const creatingNode = ref(false)
const selectedTypeId = ref('')
const selectedNodeName = ref('')
const selectedNodeSchema = ref<Record<string, any>>({})
const selectedNodeFields = ref<Record<string, any>>({})
const {
  modeOptions,
  toolOptions,
  createProviderOptions,
  ensureCreateAgentSelections,
} = useAgentNodeCreateSchema({
  selectedTypeId,
  selectedNodeFields,
  providers,
  availableTools,
})

function capabilityList(values: unknown): string[] {
  if (!Array.isArray(values)) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of values) {
    const text = String(item || '').trim()
    if (!text) continue
    const key = text.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(text)
  }
  return out
}

function shortCapability(value: string) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (text.startsWith('resource:')) return `res:${text.slice('resource:'.length)}`
  return text
}

function setSelectedNodeField(key: string, value: any) {
  selectedNodeFields.value = { ...selectedNodeFields.value, [key]: value }
}

async function onNodeClick(node: { id: string; name: string }) {
  lastError.value = null
  nodeDialogLoading.value = true
  try {
    const tpl = await getNodeTemplate(node.id)
    selectedTypeId.value = node.id
    selectedNodeName.value = String(tpl.name || node.name || node.id)
    selectedNodeSchema.value = (tpl.schema || {}) as Record<string, any>
    selectedNodeFields.value = { ...(tpl.fields || {}) }
    ensureCreateAgentSelections()
    showNodeDialog.value = true
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  } finally {
    nodeDialogLoading.value = false
  }
}

async function confirmCreateNode() {
  if (!selectedTypeId.value) return
  creatingNode.value = true
  lastError.value = null
  try {
    const fields: Record<string, unknown> = {}
    for (const key of Object.keys(selectedNodeFields.value || {})) {
      const raw = selectedNodeFields.value[key]
      fields[key] = normalizeSchemaFieldValue(selectedNodeSchema.value, key, raw)
    }
    await ctx.createNodeFromPalette(selectedTypeId.value, selectedNodeName.value, fields)
    showNodeDialog.value = false
  } catch (e: any) {
    lastError.value = String(e?.message || e)
  } finally {
    creatingNode.value = false
  }
}

watch(
  () => [
    selectedTypeId.value,
    modeOptions.value.join('|'),
    createProviderOptions.value.join('|'),
    toolOptions.value.join('|'),
    String(selectedNodeFields.value.mode ?? ''),
  ],
  () => {
    ensureCreateAgentSelections()
  },
)
</script>

<template>
  <div class="node-palette">
    <div class="node-palette-head">
      <div class="node-palette-title">鑺傜偣鍒涘缓</div>
      <button class="graph-entry" @click="ctx.openGraphPanel">
        Graph: {{ ctx.currentGraphName.value || ctx.currentGraphId.value || 'default' }}
      </button>
    </div>

    <div class="node-palette-list">
      <button
        v-for="node in ctx.availableNodes.value"
        :key="node.id"
        class="node-palette-item"
        :disabled="nodeDialogLoading"
        @click="onNodeClick(node)"
      >
        <div class="node-palette-name">{{ node.name }}</div>
        <div v-if="node.description" class="node-palette-desc">{{ node.description }}</div>
        <div v-if="capabilityList((node as any).accepts).length || capabilityList((node as any).produces).length" class="node-caps">
          <div v-if="capabilityList((node as any).accepts).length" class="node-cap-row">
            <span class="node-cap-label">in</span>
            <span
              v-for="cap in capabilityList((node as any).accepts)"
              :key="`${node.id}-in-${cap}`"
              class="node-cap-chip"
            >{{ shortCapability(cap) }}</span>
          </div>
          <div v-if="capabilityList((node as any).produces).length" class="node-cap-row">
            <span class="node-cap-label">out</span>
            <span
              v-for="cap in capabilityList((node as any).produces)"
              :key="`${node.id}-out-${cap}`"
              class="node-cap-chip out"
            >{{ shortCapability(cap) }}</span>
          </div>
        </div>
      </button>
      <div v-if="ctx.availableNodes.value.length === 0" class="node-palette-empty">娌℃湁鍙敤鑺傜偣</div>
    </div>

    <Teleport to="body">
      <div v-if="showNodeDialog" class="modal-overlay" @click.self="showNodeDialog = false">
        <div class="modal">
          <h3>鍒涘缓鑺傜偣</h3>
          <label class="field">
            <span class="field-label">鑺傜偣鍚嶇О</span>
            <input v-model="selectedNodeName" class="field-input" type="text" />
          </label>

          <NodeConfigFields
            :type-id="selectedTypeId"
            :schema="selectedNodeSchema"
            :fields="selectedNodeFields"
            :providers="providers"
            :available-tools="availableTools"
            @update-field="setSelectedNodeField"
          />

          <div class="modal-actions">
            <button @click="showNodeDialog = false">鍙栨秷</button>
            <button class="primary" :disabled="creatingNode" @click="confirmCreateNode">纭鍒涘缓</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.node-palette {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  background: rgba(11, 15, 23, 0.4);
}

.node-palette-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.node-palette-title {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.7);
  margin-right: auto;
}

.graph-entry {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.2);
  color: rgba(255, 255, 255, 0.85);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.node-palette-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.node-palette-item {
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  padding: 6px 10px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: left;
  color: inherit;
}

.node-palette-name {
  font-size: 12px;
  color: #fff;
}

.node-palette-desc {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.7);
}

.node-caps {
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.node-cap-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.node-cap-label {
  font-size: 10px;
  color: rgba(148, 163, 184, 0.85);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.node-cap-chip {
  font-size: 10px;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 999px;
  border: 1px solid rgba(125, 211, 252, 0.36);
  color: rgba(186, 230, 253, 0.98);
  background: rgba(14, 116, 144, 0.2);
}

.node-cap-chip.out {
  border-color: rgba(74, 222, 128, 0.34);
  color: rgba(187, 247, 208, 0.98);
  background: rgba(22, 101, 52, 0.2);
}

.node-palette-empty {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.6);
  padding: 6px 2px;
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background-color: #1e293b;
  padding: 24px;
  border-radius: 8px;
  width: 520px;
  max-width: 92%;
  max-height: 86vh;
  overflow: auto;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
}

.modal h3 {
  margin-top: 0;
  margin-bottom: 16px;
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

.field-checkbox {
  width: 16px;
  height: 16px;
}

.field-label {
  font-size: 12px;
  color: #94a3b8;
}

.field-hint {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.7);
  line-height: 1.35;
}

.field-input {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 6px;
  padding: 8px 10px;
  color: #e2e8f0;
  font-size: 13px;
}

.field-textarea {
  resize: vertical;
  min-height: 72px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.modal-actions button.primary {
  background: rgba(99, 102, 241, 0.4);
  border: 1px solid rgba(99, 102, 241, 0.7);
}
</style>
