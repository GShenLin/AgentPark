<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { AgentBoardKey } from './agent-board/context'
import {
  getSchemaFieldOptions,
  isSchemaMultiSelectField,
  isSchemaSelectField,
  normalizeSchemaFieldValue,
} from '../composables/nodeSchemaFields'

const injected = inject(AgentBoardKey, null)
if (!injected) {
  throw new Error('AgentBoard context not found')
}
const ctx = injected

const isCollapsed = ref(true)
const draftFields = ref<Record<string, any>>({})
const dirtyKeys = ref<Record<string, true>>({})
const editingKey = ref<string | null>(null)
const syncLock = ref(0)

const selectedNode = computed(() => {
  const id = ctx.selectedNodeId.value
  if (!id) return null
  return ctx.nodes.value.find((n) => n.id === id) || null
})

const selectedConfig = computed(() => {
  const id = ctx.selectedNodeId.value
  if (!id) return null
  return ctx.nodeConfigs.value[id] || null
})

const schema = computed(() => {
  const cfg: any = selectedConfig.value as any
  const value = cfg?.schema
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
})

const fieldKeys = computed(() => {
  return Object.keys(schema.value || {})
})

function toggleCollapsed() {
  isCollapsed.value = !isCollapsed.value
}

function setDirty(key: string) {
  if (dirtyKeys.value[key]) return
  dirtyKeys.value = { ...dirtyKeys.value, [key]: true }
}

function setField(key: string, value: any) {
  draftFields.value = { ...draftFields.value, [key]: value }
  setDirty(key)
}

function onFieldFocus(key: string) {
  editingKey.value = key
}

async function commitField(key: string) {
  const nodeId = ctx.selectedNodeId.value
  if (!nodeId) return
  if (!dirtyKeys.value[key]) return

  const value = normalizeSchemaFieldValue(schema.value, key, (draftFields.value as any)?.[key])
  syncLock.value += 1
  try {
    await ctx.setNodeFields(nodeId, { [key]: value })
    const nextDirty = { ...dirtyKeys.value }
    delete nextDirty[key]
    dirtyKeys.value = nextDirty
  } catch (e: any) {
    ctx.lastError.value = String(e?.message || e)
  } finally {
    syncLock.value = Math.max(0, syncLock.value - 1)
  }
}

async function commitAll(nodeId: string) {
  if (!nodeId) return
  const keys = Object.keys(dirtyKeys.value || {})
  if (!keys.length) return

  const fields: Record<string, unknown> = {}
  for (const k of keys) fields[k] = (draftFields.value as any)?.[k]
  syncLock.value += 1
  try {
    await ctx.setNodeFields(nodeId, fields)
    dirtyKeys.value = {}
  } catch (e: any) {
    ctx.lastError.value = String(e?.message || e)
  } finally {
    syncLock.value = Math.max(0, syncLock.value - 1)
  }
}

function getFieldLabel(key: string) {
  const entry = (schema.value as any)?.[key]
  const label = entry && typeof entry === 'object' ? entry.label : null
  return label != null && String(label).trim() ? String(label) : key
}

function getFieldType(key: string) {
  const entry = (schema.value as any)?.[key]
  const type = entry && typeof entry === 'object' ? entry.type : null
  return type != null && String(type).trim() ? String(type) : 'text'
}

function getInputType(key: string) {
  return getFieldType(key) === 'number' ? 'number' : 'text'
}

function isSelectField(key: string) {
  return isSchemaSelectField(schema.value, key)
}

function isMultiSelectField(key: string) {
  return isSchemaMultiSelectField(schema.value, key)
}

function getFieldOptions(key: string) {
  return getSchemaFieldOptions(schema.value, key)
}

function isCheckedValue(value: unknown) {
  if (typeof value === 'boolean') return value
  const text = String(value ?? '').trim().toLowerCase()
  return ['true', '1', 'yes', 'on', 'enabled'].includes(text)
}

function getDraftValue(key: string) {
  return String((draftFields.value as any)?.[key] ?? '')
}

function getMultiSelectValue(key: string) {
  return normalizeSchemaFieldValue(schema.value, key, (draftFields.value as any)?.[key]) as string[]
}

function getMultiSelectPlaceholder(key: string) {
  if (key === 'plugins') return 'Select plugins'
  if (key === 'tools') return 'Select tools'
  if (key === 'mcp_servers') return 'Select MCP servers'
  if (key === 'skills') return 'Select skills'
  return `Select ${getFieldLabel(key)}`
}

function getMultiSelectLabel(key: string) {
  const selected = new Set(getMultiSelectValue(key))
  const labels = getFieldOptions(key)
    .filter((option) => selected.has(option.value))
    .map((option) => option.label)
  if (!labels.length) return getMultiSelectPlaceholder(key)
  if (labels.length <= 2) return labels.join(', ')
  return `${labels.length} selected`
}

function getMultiSelectEmptyText(key: string) {
  if (key === 'plugins') return 'No plugins found.'
  if (key === 'tools') return 'No tools found.'
  if (key === 'mcp_servers') return 'No MCP servers found.'
  if (key === 'skills') return 'No skills found.'
  return 'No options found.'
}

function toggleMultiSelectOption(key: string, value: string) {
  const optionValue = String(value || '').trim()
  if (!optionValue) return
  const current = getMultiSelectValue(key)
  const next = current.includes(optionValue)
    ? current.filter((item) => item !== optionValue)
    : [...current, optionValue]
  setField(key, next)
}

watch(
  () => ctx.selectedNodeId.value,
  async (id, prevId) => {
    if (prevId) {
      editingKey.value = null
      await commitAll(prevId)
    }
    if (!id) return
    dirtyKeys.value = {}
    await ctx.refreshNodeConfig(id).catch(() => null)
  },
)

watch(
  () => selectedConfig.value,
  (cfg) => {
    if (editingKey.value != null) return
    if (syncLock.value > 0) return
    const next: Record<string, any> = {}
    for (const key of Object.keys(schema.value || {})) {
      next[key] = (cfg as any)?.[key]
    }
    draftFields.value = next
  },
  { immediate: true },
)
</script>

<template>
  <aside class="creator-panel" :class="{ collapsed: isCollapsed }">
    <div class="creator-head">
      <div class="creator-title">NodeInspector</div>
      <button class="creator-toggle" @click="toggleCollapsed">{{ isCollapsed ? '展开' : '收起' }}</button>
    </div>

    <div v-if="!isCollapsed" class="creator-body">
      <div v-if="!selectedNode" class="empty-hint">未选择节点</div>
      <template v-else>
        <div class="node-meta">
          <div class="node-meta-title">{{ selectedNode.name }}</div>
          <div class="node-meta-sub">{{ selectedNode.typeId }} · {{ selectedNode.id }}</div>
        </div>

        <div v-if="fieldKeys.length === 0" class="empty-hint">这个节点没有可编辑属性</div>

        <label v-for="key in fieldKeys" :key="key" class="field" :class="{ 'field-check': getFieldType(key) === 'boolean' }">
          <span class="field-label">{{ getFieldLabel(key) }}</span>

          <details
            v-if="isMultiSelectField(key)"
            class="multi-select-dropdown"
            @focus="onFieldFocus(key)"
          >
            <summary class="field-input multi-select-summary">{{ getMultiSelectLabel(key) }}</summary>
            <div class="multi-select-menu">
              <div
                v-for="option in getFieldOptions(key)"
                :key="`inspect-multi-${key}-${option.value}`"
                class="multi-select-option"
                role="checkbox"
                tabindex="0"
                :aria-checked="getMultiSelectValue(key).includes(option.value)"
                @click="toggleMultiSelectOption(key, option.value); editingKey = null; commitField(key)"
                @keydown.enter.prevent="toggleMultiSelectOption(key, option.value); editingKey = null; commitField(key)"
                @keydown.space.prevent="toggleMultiSelectOption(key, option.value); editingKey = null; commitField(key)"
              >
                <input
                  type="checkbox"
                  :checked="getMultiSelectValue(key).includes(option.value)"
                  tabindex="-1"
                  @click.stop="toggleMultiSelectOption(key, option.value); editingKey = null; commitField(key)"
                  @change.stop
                />
                <span>{{ option.label }}</span>
              </div>
              <div v-if="getFieldOptions(key).length === 0" class="multi-select-empty">{{ getMultiSelectEmptyText(key) }}</div>
            </div>
          </details>

          <select
            v-else-if="isSelectField(key)"
            class="field-input"
            :value="getDraftValue(key)"
            @focus="onFieldFocus(key)"
            @change="setField(key, ($event.target as HTMLSelectElement).value); editingKey = null; commitField(key)"
          >
            <option v-for="option in getFieldOptions(key)" :key="`inspect-${key}-${option.value}`" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <textarea
            v-else-if="getFieldType(key) === 'text'"
            class="field-input field-textarea"
            rows="3"
            :value="getDraftValue(key)"
            @focus="onFieldFocus(key)"
            @input="setField(key, ($event.target as HTMLTextAreaElement).value)"
            @blur="editingKey = null; commitField(key)"
          />
          <input
            v-else-if="getFieldType(key) === 'boolean'"
            class="field-checkbox"
            type="checkbox"
            :checked="isCheckedValue(draftFields[key])"
            @change="setField(key, ($event.target as HTMLInputElement).checked); editingKey = null; commitField(key)"
          />
          <input
            v-else
            class="field-input"
            :type="getInputType(key)"
            :value="getDraftValue(key)"
            @focus="onFieldFocus(key)"
            @input="setField(key, ($event.target as HTMLInputElement).value)"
            @keydown.enter.prevent="commitField(key).finally(() => ($event.target as HTMLInputElement).blur())"
            @blur="editingKey = null; commitField(key)"
          />
        </label>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.node-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
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

.node-meta-title {
  font-weight: 600;
  font-size: 14px;
  color: #e2e8f0;
}

.node-meta-sub {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.75);
  word-break: break-all;
}

.empty-hint {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.7);
}

.multi-select-dropdown {
  position: relative;
}

.multi-select-summary {
  cursor: pointer;
  list-style: none;
  min-height: 38px;
}

.multi-select-summary::-webkit-details-marker {
  display: none;
}

.multi-select-summary::after {
  content: 'v';
  float: right;
  color: rgba(148, 163, 184, 0.9);
}

.multi-select-dropdown[open] .multi-select-summary::after {
  content: '^';
}

.multi-select-menu {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
  max-height: 180px;
  overflow: auto;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.98);
  padding: 8px;
  position: absolute;
  z-index: 20;
  width: 100%;
  box-shadow: 0 14px 30px rgba(0, 0, 0, 0.3);
}

.multi-select-option {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  color: rgba(226, 232, 240, 0.95);
  line-height: 1.35;
}

.multi-select-option input {
  margin-top: 2px;
}

.multi-select-empty {
  font-size: 12px;
  color: rgba(148, 163, 184, 0.78);
}
</style>
