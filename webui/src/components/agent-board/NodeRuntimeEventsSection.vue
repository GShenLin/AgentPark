<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  applyRuntimeEventConfig,
  listAgentProfiles,
  listNodeInstanceFiles,
  loadRuntimeEventConfig,
  loadRuntimeEventSchema,
  type AgentProfile,
  type RuntimeEventConfig,
  type RuntimeEventRule,
  type RuntimeEventSchema,
} from '../../api'
import {
  actionLabel,
  addRuntimeEventHandler,
  addRuntimeEventNode,
  cloneRuntimeEventConfig,
  defaultTargetForAction,
  deleteRuntimeEventHandler,
  deleteRuntimeEventNode,
  ensureCompanionReceiverGroup,
  eventNodesForNode,
  formatRuntimeApplyErrors,
  makeRuntimeEventRule,
  replaceRuntimeEventHandler,
  targetOptionsForAction,
} from '../../runtimeEventsConfig'
import NodeAppendFilePickerSheet from './NodeAppendFilePickerSheet.vue'
import type { NodeCard } from './context'

const COMPANION_GROUP_ID = 'companion'
const CONTEXT_ROLE_LABELS: Record<string, string> = {
  developer: 'Developer',
  system: 'System',
  user: 'User',
  assistant: 'Assistant',
}

const props = defineProps<{
  node: Pick<NodeCard, 'id'>
  graphId: string
}>()
const emit = defineEmits<{ error: [message: string] }>()

const loading = ref(false)
const applying = ref(false)
const config = ref<RuntimeEventConfig | null>(null)
const schema = ref<RuntimeEventSchema | null>(null)
const agentProfiles = ref<AgentProfile[]>([])
const status = ref('')
const selectingFile = ref('')
const appendFilePickerOpen = ref(false)
const appendFilePickerKey = ref('')
const appendFilePickerDraft = ref('')
const appendFilePickerSelected = ref<string[]>([])
const appendFilePickerFiles = ref<Array<{ name: string; path: string; size: number }>>([])
const appendFilePickerLoading = ref(false)

const eventNodes = computed(() => config.value ? eventNodesForNode(config.value, props.graphId, props.node.id) : [])
const eventOptions = computed(() => schema.value?.events || [])
const actionOptions = computed(() => schema.value?.actions || [])
const contextRoleOptions = computed(() => schema.value?.context_roles || Object.keys(CONTEXT_ROLE_LABELS))
const profileOptions = computed(() => agentProfiles.value.map((profile) => profile.id).filter(Boolean).sort())

function showError(message: string) {
  emit('error', message)
}

function targetOptions(action: string) {
  return config.value ? targetOptionsForAction(config.value, action) : []
}

function actionsForEvent(_event: string) {
  return actionOptions.value
}

function appendFilePaths(paths: unknown): string[] {
  if (!Array.isArray(paths)) return []
  return paths.map((path) => String(path || '').trim()).filter(Boolean)
}

function appendFileLabel(paths: unknown) {
  const selected = appendFilePaths(paths)
  if (!selected.length) return '选择文件'
  if (selected.length > 1) return `${selected.length} 个文件`
  const normalized = String(selected[0] || '').replace(/[\\/]+$/, '')
  return normalized.split(/[\\/]/).pop() || normalized
}

function availableEventsFor(index: number) {
  const used = new Set(eventNodes.value.filter((_item, itemIndex) => itemIndex !== index).map((item) => item.event))
  return eventOptions.value.filter((event) => !used.has(event) || event === eventNodes.value[index]?.event)
}

async function refreshEvents() {
  loading.value = true
  showError('')
  status.value = ''
  try {
    const [document, nextSchema, profiles] = await Promise.all([
      loadRuntimeEventConfig(),
      loadRuntimeEventSchema(),
      listAgentProfiles(),
    ])
    config.value = cloneRuntimeEventConfig(document.config)
    schema.value = nextSchema
    agentProfiles.value = profiles
  } catch (error: any) {
    showError(String(error?.message || error))
  } finally {
    loading.value = false
  }
}

async function applyConfig(next: RuntimeEventConfig, message: string): Promise<boolean> {
  applying.value = true
  showError('')
  status.value = ''
  try {
    const result = await applyRuntimeEventConfig(next)
    if (!result.ok) throw new Error(formatRuntimeApplyErrors(result.errors))
    config.value = cloneRuntimeEventConfig(next)
    const warnings = Array.isArray(result.warnings)
      ? result.warnings.map((item) => String(item || '').trim()).filter(Boolean)
      : []
    status.value = warnings.length ? `${message}；${warnings.slice(0, 2).join('；')}` : message
    return true
  } catch (error: any) {
    showError(String(error?.message || error))
    return false
  } finally {
    applying.value = false
  }
}

async function addEventNode() {
  if (!config.value) return
  const event = eventOptions.value.find((item) => !eventNodes.value.some((node) => node.event === item))
  if (!event) {
    showError('当前节点已经配置了所有可用事件。')
    return
  }
  const next = cloneRuntimeEventConfig(config.value)
  addRuntimeEventNode(next, { graphId: props.graphId, nodeId: props.node.id, event, handlers: [] })
  await applyConfig(next, `${event} 已添加，请添加处理方式`)
}

async function updateEvent(index: number, event: string) {
  if (!config.value) return
  const current = eventNodes.value[index]
  if (!current || current.event === event) return
  const next = cloneRuntimeEventConfig(config.value)
  addRuntimeEventNode(next, { graphId: current.graphId, nodeId: current.nodeId, event, handlers: current.handlers })
  deleteRuntimeEventNode(next, current)
  await applyConfig(next, `事件已改为 ${event}`)
}

function defaultHandler(next: RuntimeEventConfig, event: string): RuntimeEventRule | null {
  for (const action of actionsForEvent(event)) {
    let target = defaultTargetForAction(next, action)
    if (action === 'node.dispatch') {
      const profileId = profileOptions.value[0]
      if (!profileId) continue
      target = target || COMPANION_GROUP_ID
      ensureCompanionReceiverGroup(next, target)
      return makeRuntimeEventRule({ action, target, event: '', params: { profile_ids: [profileId] } })
    }
    if (action === 'context.append_file') {
      return makeRuntimeEventRule({ action, target: '', event: '', params: { paths: [], role: 'developer' }, enabled: false })
    }
    if (target) return makeRuntimeEventRule({ action, target, event: '' })
  }
  return null
}

async function addHandler(eventIndex: number) {
  if (!config.value) return
  const eventNode = eventNodes.value[eventIndex]
  if (!eventNode) return
  const next = cloneRuntimeEventConfig(config.value)
  const handler = defaultHandler(next, eventNode.event)
  if (!handler) {
    showError('没有可用的事件处理方式或处理目标。')
    return
  }
  addRuntimeEventHandler(next, { ...eventNode, handler })
  await applyConfig(next, `${eventNode.event} 已添加处理方式`)
}

async function updateHandler(eventIndex: number, handlerIndex: number, patch: Partial<RuntimeEventRule>): Promise<boolean> {
  if (!config.value) return false
  const eventNode = eventNodes.value[eventIndex]
  const current = eventNode?.handlers[handlerIndex]
  if (!eventNode || !current) return false
  const next = cloneRuntimeEventConfig(config.value)
  replaceRuntimeEventHandler(next, {
    ...eventNode,
    handlerIndex,
    handler: { ...current, ...patch },
  })
  return applyConfig(next, `${eventNode.event} 的处理方式已更新`)
}

async function updateAction(eventIndex: number, handlerIndex: number, action: string) {
  if (!config.value) return
  const next = cloneRuntimeEventConfig(config.value)
  let target = defaultTargetForAction(next, action)
  let params: RuntimeEventRule['params'] = {}
  if (action === 'node.dispatch') {
    const profileId = profileOptions.value[0]
    if (!profileId) {
      showError('没有可用的 Agent Profile，无法选择“交给 Agent 处理”。')
      return
    }
    target = target || COMPANION_GROUP_ID
    ensureCompanionReceiverGroup(next, target)
    params = { profile_ids: [profileId] }
  } else if (action === 'context.append_file') {
    target = ''
    params = { paths: [], role: 'developer' }
  }
  if (!target && action !== 'context.append_file') {
    showError(`事件处理方式 ${actionLabel(action)} 没有可用目标。`)
    return
  }
  const eventNode = eventNodes.value[eventIndex]
  const current = eventNode?.handlers[handlerIndex]
  if (!eventNode || !current) return
  const enabled = action === 'context.append_file'
    ? false
    : current.action === 'context.append_file'
      ? true
      : current.enabled !== false
  replaceRuntimeEventHandler(next, {
    ...eventNode,
    handlerIndex,
    handler: { ...current, action, target, params, enabled },
  })
  await applyConfig(next, `${eventNode.event} 的处理方式已更新`)
}

async function chooseAppendFile(eventIndex: number, handlerIndex: number) {
  const current = eventNodes.value[eventIndex]?.handlers[handlerIndex]
  if (!current) return
  const key = `${eventIndex}/${handlerIndex}`
  appendFilePickerKey.value = key
  appendFilePickerDraft.value = ''
  appendFilePickerSelected.value = appendFilePaths(current.params?.paths)
  appendFilePickerFiles.value = []
  appendFilePickerOpen.value = true
  appendFilePickerLoading.value = true
  selectingFile.value = key
  showError('')
  try {
    const result = await listNodeInstanceFiles(props.node.id, props.graphId)
    if (appendFilePickerKey.value !== key) return
    appendFilePickerFiles.value = Array.isArray(result.files) ? result.files : []
  } catch (error: any) {
    showError(String(error?.message || error))
  } finally {
    if (appendFilePickerKey.value === key) appendFilePickerLoading.value = false
    selectingFile.value = ''
  }
}

function closeAppendFilePicker() {
  appendFilePickerOpen.value = false
  appendFilePickerKey.value = ''
  appendFilePickerDraft.value = ''
  appendFilePickerSelected.value = []
  appendFilePickerFiles.value = []
  appendFilePickerLoading.value = false
  selectingFile.value = ''
}

async function confirmAppendFile() {
  const [eventIndexText, handlerIndexText] = appendFilePickerKey.value.split('/')
  const eventIndex = Number(eventIndexText)
  const handlerIndex = Number(handlerIndexText)
  const current = eventNodes.value[eventIndex]?.handlers[handlerIndex]
  if (!current) {
    closeAppendFilePicker()
    return
  }
  const selected = [...appendFilePickerSelected.value]
  const draftPath = appendFilePickerDraft.value.trim().replace(/\\/g, '/')
  if (draftPath) {
    if (draftPath.startsWith('/') || /^[A-Za-z]:\//.test(draftPath) || draftPath.split('/').includes('..')) {
      showError('只能填写当前节点目录下的相对文件路径。')
      return
    }
    if (!selected.includes(draftPath)) selected.push(draftPath)
  }
  if (!selected.length) {
    showError('请至少选择或填写一个节点文件。')
    return
  }
  const saved = await updateHandler(eventIndex, handlerIndex, {
    enabled: true,
    params: { ...(current.params || {}), paths: selected },
  })
  if (saved) closeAppendFilePicker()
}

async function addProfile(eventIndex: number, handlerIndex: number) {
  const current = eventNodes.value[eventIndex]?.handlers[handlerIndex]
  if (!current) return
  const selected = Array.isArray(current.params?.profile_ids) ? current.params.profile_ids : []
  const profileId = profileOptions.value.find((item) => !selected.includes(item))
  if (!profileId) {
    showError('已经添加了所有可用的 Agent Profile。')
    return
  }
  await updateHandler(eventIndex, handlerIndex, {
    params: { ...(current.params || {}), profile_ids: [...selected, profileId] },
  })
}

async function updateProfile(eventIndex: number, handlerIndex: number, profileIndex: number, profileId: string) {
  const current = eventNodes.value[eventIndex]?.handlers[handlerIndex]
  if (!current || !profileId) return
  const profileIds = Array.isArray(current.params?.profile_ids) ? [...current.params.profile_ids] : []
  profileIds[profileIndex] = profileId
  await updateHandler(eventIndex, handlerIndex, {
    params: { ...(current.params || {}), profile_ids: profileIds },
  })
}

async function deleteProfile(eventIndex: number, handlerIndex: number, profileIndex: number) {
  const current = eventNodes.value[eventIndex]?.handlers[handlerIndex]
  if (!current) return
  const profileIds = Array.isArray(current.params?.profile_ids) ? current.params.profile_ids : []
  if (profileIds.length <= 1) {
    showError('交给 Agent 处理至少需要一个 Agent Profile。')
    return
  }
  await updateHandler(eventIndex, handlerIndex, {
    params: { ...(current.params || {}), profile_ids: profileIds.filter((_item, index) => index !== profileIndex) },
  })
}

async function deleteHandler(eventIndex: number, handlerIndex: number) {
  if (!config.value) return
  const eventNode = eventNodes.value[eventIndex]
  if (!eventNode) return
  const next = cloneRuntimeEventConfig(config.value)
  deleteRuntimeEventHandler(next, { ...eventNode, handlerIndex })
  await applyConfig(next, `${eventNode.event} 的处理方式已删除`)
}

async function deleteEventNode(index: number) {
  if (!config.value) return
  const eventNode = eventNodes.value[index]
  if (!eventNode) return
  const next = cloneRuntimeEventConfig(config.value)
  deleteRuntimeEventNode(next, eventNode)
  await applyConfig(next, `${eventNode.event} 已删除`)
}

watch(() => [props.graphId, props.node.id], refreshEvents)
onMounted(refreshEvents)
</script>

<template>
  <section class="runtime-events-section">
    <div class="section-head">
      <div>
        <div class="section-title">事件处理</div>
        <div class="section-subtitle">事件与多个处理方式统一保存到 config/events.json</div>
      </div>
      <div class="section-actions">
        <button class="mini-btn" type="button" :disabled="loading || applying" @click="refreshEvents">{{ loading ? '加载中...' : '刷新' }}</button>
        <button class="mini-btn primary" type="button" :disabled="loading || applying" title="添加事件" @click="addEventNode">+</button>
      </div>
    </div>

    <div v-if="status" class="event-status">{{ status }}</div>
    <div v-if="loading" class="empty-hint">正在加载事件配置...</div>
    <div v-else-if="eventNodes.length" class="event-node-list">
      <div v-for="(eventNode, eventIndex) in eventNodes" :key="eventNode.event" class="event-node">
        <div class="event-column">
          <select :value="eventNode.event" :disabled="applying" aria-label="事件" @change="updateEvent(eventIndex, ($event.target as HTMLSelectElement).value)">
            <option v-for="event in availableEventsFor(eventIndex)" :key="event" :value="event">{{ event }}</option>
          </select>
          <button class="icon-btn danger" type="button" :disabled="applying" title="删除事件" @click="deleteEventNode(eventIndex)">×</button>
        </div>

        <div class="handler-column">
          <div class="handler-head">
            <span>处理方式</span>
            <button class="icon-btn add" type="button" :disabled="applying" title="添加处理方式" @click="addHandler(eventIndex)">+</button>
          </div>
          <div v-if="eventNode.handlers.length" class="handler-list">
            <div v-for="(handler, handlerIndex) in eventNode.handlers" :key="handlerIndex" class="handler-row">
              <select :value="handler.action" :disabled="applying" aria-label="处理方式" @change="updateAction(eventIndex, handlerIndex, ($event.target as HTMLSelectElement).value)">
                <option v-for="action in actionsForEvent(eventNode.event)" :key="action" :value="action">{{ actionLabel(action) }}</option>
              </select>
              <div v-if="handler.action === 'node.dispatch'" class="profile-list">
                <div v-for="(selectedProfileId, profileIndex) in handler.params?.profile_ids || []" :key="`${selectedProfileId}/${profileIndex}`" class="profile-row">
                  <select :value="selectedProfileId" :disabled="applying" aria-label="处理 Agent" @change="updateProfile(eventIndex, handlerIndex, profileIndex, ($event.target as HTMLSelectElement).value)">
                    <option v-for="profileId in profileOptions" :key="profileId" :value="profileId" :disabled="profileId !== selectedProfileId && (handler.params?.profile_ids || []).includes(profileId)">{{ profileId }}</option>
                  </select>
                  <button class="icon-btn danger" type="button" :disabled="applying" title="删除 Agent Profile" @click="deleteProfile(eventIndex, handlerIndex, profileIndex)">×</button>
                </div>
                <button class="mini-btn" type="button" :disabled="applying" @click="addProfile(eventIndex, handlerIndex)">+ Agent Profile</button>
              </div>
              <div v-else-if="handler.action === 'context.append_file'" class="append-file-field">
                <button
                  class="mini-btn append-file-btn"
                  type="button"
                  :disabled="applying || selectingFile === `${eventIndex}/${handlerIndex}`"
                  :title="appendFilePaths(handler.params?.paths).join('\n') || '选择一个或多个上下文文件'"
                  @click="chooseAppendFile(eventIndex, handlerIndex)"
                >{{ selectingFile === `${eventIndex}/${handlerIndex}` ? '选择中...' : appendFileLabel(handler.params?.paths) }}</button>
                <select
                  :value="String(handler.params?.role || 'developer')"
                  :disabled="applying"
                  aria-label="上下文角色"
                  @change="updateHandler(eventIndex, handlerIndex, { params: { ...(handler.params || {}), role: ($event.target as HTMLSelectElement).value } })"
                >
                  <option v-for="role in contextRoleOptions" :key="role" :value="role">{{ CONTEXT_ROLE_LABELS[role] || role }}</option>
                </select>
              </div>
              <select v-else :value="handler.target" :disabled="applying" aria-label="处理目标" @change="updateHandler(eventIndex, handlerIndex, { target: ($event.target as HTMLSelectElement).value })">
                <option v-for="target in targetOptions(handler.action)" :key="target" :value="target">{{ target }}</option>
              </select>
              <label
                class="handler-enabled"
                :class="{ disabled: handler.action === 'context.append_file' && !appendFilePaths(handler.params?.paths).length }"
                :title="handler.action === 'context.append_file' && !appendFilePaths(handler.params?.paths).length ? '请先选择上下文文件' : '控制该处理方式是否执行'"
              >
                <input
                  type="checkbox"
                  :checked="handler.enabled !== false"
                  :disabled="applying || (handler.action === 'context.append_file' && !appendFilePaths(handler.params?.paths).length)"
                  :aria-label="`${actionLabel(handler.action)} 是否启用`"
                  @change="updateHandler(eventIndex, handlerIndex, { enabled: ($event.target as HTMLInputElement).checked })"
                />
                <span>启用</span>
              </label>
              <button class="icon-btn danger" type="button" :disabled="applying" title="删除处理方式" @click="deleteHandler(eventIndex, handlerIndex)">×</button>
            </div>
          </div>
          <div v-else class="empty-handler">暂无处理方式，点击右上角 + 添加。</div>
        </div>
      </div>
    </div>
    <div v-else class="empty-state">
      <span>当前节点没有事件配置。</span>
      <button class="mini-btn primary" type="button" :disabled="applying" @click="addEventNode">+ 添加事件</button>
    </div>

    <NodeAppendFilePickerSheet
      v-if="appendFilePickerOpen"
      v-model:custom-path="appendFilePickerDraft"
      v-model:selected-paths="appendFilePickerSelected"
      :files="appendFilePickerFiles"
      :loading="appendFilePickerLoading"
      :saving="applying"
      @close="closeAppendFilePicker"
      @confirm="confirmAppendFile"
    />
  </section>
</template>

<style scoped>
.runtime-events-section { display: flex; flex-direction: column; gap: 10px; flex: 0 0 auto; border-top: 1px solid rgba(148, 163, 184, 0.2); padding-top: 12px; }
.section-head, .section-actions, .handler-head, .event-column { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.section-title { font-size: 13px; font-weight: 700; color: #e2e8f0; }
.section-subtitle, .empty-hint, .empty-handler { margin-top: 2px; color: rgba(148, 163, 184, 0.84); font-size: 11px; }
.event-node-list, .handler-list { display: flex; flex-direction: column; gap: 8px; }
.event-node { display: grid; grid-template-columns: minmax(130px, 0.7fr) minmax(0, 2fr); gap: 10px; border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 8px; padding: 8px; }
.event-column { align-items: flex-start; }
.event-column select { flex: 1; }
.handler-column { min-width: 0; border-left: 1px solid rgba(148, 163, 184, 0.14); padding-left: 10px; }
.handler-head { margin-bottom: 8px; color: rgba(203, 213, 225, 0.9); font-size: 11px; }
.handler-row { display: grid; grid-template-columns: minmax(118px, 0.9fr) minmax(132px, 1.1fr) auto auto; gap: 8px; align-items: center; }
.profile-list, .profile-row { display: flex; gap: 6px; align-items: center; }
.profile-list { flex-direction: column; align-items: stretch; }
.profile-row select { flex: 1; }
.append-file-field { display: grid; grid-template-columns: minmax(0, 1fr) minmax(105px, 0.45fr); gap: 6px; }
.append-file-btn { min-width: 0; overflow: hidden; text-align: left; text-overflow: ellipsis; }
.handler-enabled { display: inline-flex; align-items: center; gap: 5px; color: #cbd5e1; cursor: pointer; font-size: 11px; white-space: nowrap; }
.handler-enabled input { margin: 0; accent-color: #14b8a6; }
.handler-enabled.disabled { cursor: default; opacity: 0.55; }
.empty-handler { border: 1px dashed rgba(148, 163, 184, 0.2); border-radius: 7px; padding: 9px; }
select { min-width: 0; width: 100%; border: 1px solid rgba(148, 163, 184, 0.26); border-radius: 7px; background: rgba(15, 23, 42, 0.92); color: #f8fafc; padding: 7px 8px; font-size: 12px; }
.mini-btn, .icon-btn { border: 1px solid rgba(148, 163, 184, 0.26); border-radius: 8px; background: rgba(15, 23, 42, 0.92); color: #f8fafc; cursor: pointer; padding: 6px 9px; font-size: 12px; white-space: nowrap; }
.mini-btn.primary, .icon-btn.add { border-color: rgba(45, 212, 191, 0.35); background: rgba(13, 148, 136, 0.2); }
.icon-btn { width: 30px; height: 30px; padding: 0; font-size: 18px; }
.danger { border-color: rgba(248, 113, 113, 0.35); color: #fecaca; }
.mini-btn:disabled, .icon-btn:disabled, select:disabled { cursor: default; opacity: 0.55; }
.empty-state { display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px dashed rgba(148, 163, 184, 0.22); border-radius: 8px; color: rgba(148, 163, 184, 0.9); font-size: 12px; padding: 10px; }
.event-status { border: 1px solid rgba(45, 212, 191, 0.24); border-radius: 8px; background: rgba(15, 118, 110, 0.14); color: #ccfbf1; font-size: 12px; padding: 8px 10px; }
@media (max-width: 760px) { .event-node, .handler-row { grid-template-columns: 1fr; } .handler-column { border-left: 0; border-top: 1px solid rgba(148, 163, 184, 0.14); padding: 10px 0 0; } .handler-row > .icon-btn { width: 100%; } }
</style>
