import { computed, onMounted, ref, watch } from 'vue'
import {
  applyRuntimeEventConfig,
  deleteRuntimeEventConfigEntry,
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
  deleteRuntimeEventNode,
  ensureCompanionReceiverGroup,
  eventNodesForNode,
  formatRuntimeApplyErrors,
  makeRuntimeEventRule,
  replaceRuntimeEventHandler,
  targetOptionsForAction,
} from '../../runtimeEventsConfig'
import type { NodeCard } from './context'

const COMPANION_GROUP_ID = 'companion'


// Node editor choices are intentionally narrower than the runtime event protocol.
const NODE_EVENT_NAMES = ['OnInput', 'WorkPersisted']
const NODE_EVENT_ACTIONS = ['context.append_file', 'node.dispatch']

export function useNodeRuntimeEvents(
  props: { node: Pick<NodeCard, 'id'>; graphId: string },
  showError: (message: string) => void,
) {

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
  const eventOptions = computed(() => NODE_EVENT_NAMES.filter(event => schema.value?.events.includes(event)))
  const actionOptions = computed(() => NODE_EVENT_ACTIONS.filter(action => schema.value?.actions.includes(action)))
  const contextRoleOptions = computed(() => schema.value?.context_roles || ['developer', 'system', 'user', 'assistant'])
  const profileOptions = computed(() => agentProfiles.value.map((profile) => profile.id).filter(Boolean).sort())

  function targetOptions(action: string) {
    return config.value ? targetOptionsForAction(config.value, action) : []
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

  function defaultHandler(next: RuntimeEventConfig): RuntimeEventRule | null {
    for (const action of actionOptions.value) {
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
    const handler = defaultHandler(next)
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
    applying.value = true
    showError('')
    status.value = ''
    try {
      const result = await deleteRuntimeEventConfigEntry({
        event: eventNode.event,
        graph_id: eventNode.graphId,
        node_id: eventNode.nodeId,
        handler_index: handlerIndex,
      })
      if (!result.ok || !result.config) throw new Error(result.error || '删除事件处理方式失败')
      config.value = cloneRuntimeEventConfig(result.config)
      status.value = `${eventNode.event} 的处理方式已删除`
    } catch (error: any) {
      showError(String(error?.message || error))
    } finally {
      applying.value = false
    }
  }

  async function deleteEventNode(index: number) {
    if (!config.value) return
    const eventNode = eventNodes.value[index]
    if (!eventNode) return
    applying.value = true
    showError('')
    status.value = ''
    try {
      const result = await deleteRuntimeEventConfigEntry({
        event: eventNode.event,
        graph_id: eventNode.graphId,
        node_id: eventNode.nodeId,
      })
      if (!result.ok || !result.config) throw new Error(result.error || '删除事件失败')
      config.value = cloneRuntimeEventConfig(result.config)
      status.value = `${eventNode.event} 已删除`
    } catch (error: any) {
      showError(String(error?.message || error))
    } finally {
      applying.value = false
    }
  }

  watch(() => [props.graphId, props.node.id], () => {
    closeAppendFilePicker()
    void refreshEvents()
  })
  onMounted(refreshEvents)

  return {
    loading, applying, status, eventNodes, eventOptions, actionOptions, contextRoleOptions,
    profileOptions, selectingFile, appendFilePickerOpen, appendFilePickerDraft,
    appendFilePickerSelected, appendFilePickerFiles, appendFilePickerLoading,
    targetOptions, appendFilePaths, appendFileLabel, availableEventsFor, refreshEvents,
    addEventNode, updateEvent, addHandler, updateHandler, updateAction, chooseAppendFile,
    closeAppendFilePicker, confirmAppendFile, addProfile, updateProfile, deleteProfile,
    deleteHandler, deleteEventNode
  }
}
