import { computed, ref } from 'vue'
import { type GatewayModel, type GatewayProtocol, type GatewayProvider } from '../../gatewayApi'
import { t } from '../../i18n'

export const gatewayProtocolOptions: Array<{ id: GatewayProtocol; label: string }> = [
  { id: 'responses', label: 'Responses' },
  { id: 'chat_completions', label: 'Chat Completions' },
  { id: 'messages', label: 'Messages' },
  { id: 'images_generations', label: 'Image generation' },
  { id: 'images_edits', label: 'Image editing (JSON)' },
]

// The editor groups shared routing settings; the API stores one route per model ID.
type ProviderSettings = Omit<GatewayModel, 'id'>
type ModelIdEntry = { key: number; value: string }
type ProviderGroup = { key: number; settings: ProviderSettings; modelIds: ModelIdEntry[] }

export function useGatewayModelEditor(initialModels: GatewayModel[], providers: () => GatewayProvider[]) {
  let nextKey = 0
  const groups = ref<ProviderGroup[]>([])
  const savedModels = ref<GatewayModel[]>([])
  const savedDraft = ref('')

  function draftSnapshot() {
    return JSON.stringify(groups.value.map((group) => ({
      ...group.settings, modelIds: group.modelIds.map((entry) => entry.value),
    })))
  }

  function reset(models: GatewayModel[]) {
    savedModels.value = models.map((model) => ({ ...model, protocols: [...model.protocols] }))
    const grouped = new Map<string, ProviderGroup>()
    for (const { id, ...settings } of models) {
      const groupId = JSON.stringify([
        settings.providerId, settings.accountId, settings.enabled, [...settings.protocols].sort(),
      ])
      let group = grouped.get(groupId)
      if (!group) {
        group = { key: nextKey++, settings: { ...settings, protocols: [...settings.protocols] }, modelIds: [] }
        grouped.set(groupId, group)
      }
      group.modelIds.push({ key: nextKey++, value: id })
    }
    groups.value = [...grouped.values()]
    savedDraft.value = draftSnapshot()
  }
  reset(initialModels)

  const dirty = computed(() => draftSnapshot() !== savedDraft.value)
  const providerFor = (settings: ProviderSettings) => providers().find((provider) => provider.id === settings.providerId)

  function addGroup() {
    const provider = providers()[0]
    groups.value.push({ key: nextKey++, settings: {
      providerId: provider?.id || '', accountId: '',
      protocols: [...(provider?.protocols || [])], enabled: true,
    }, modelIds: [{ key: nextKey++, value: '' }] })
  }

  function removeGroup(key: number) {
    groups.value = groups.value.filter((group) => group.key !== key)
  }

  function addModelId(group: ProviderGroup) {
    group.modelIds.push({ key: nextKey++, value: '' })
  }

  function removeModelId(group: ProviderGroup, key: number) {
    group.modelIds = group.modelIds.filter((entry) => entry.key !== key)
  }

  function selectProvider(settings: ProviderSettings) {
    settings.accountId = ''
    settings.protocols = [...(providerFor(settings)?.protocols || [])]
  }

  function toggleProtocol(settings: ProviderSettings, protocol: GatewayProtocol, checked: boolean) {
    settings.protocols = checked
      ? Array.from(new Set([...settings.protocols, protocol]))
      : settings.protocols.filter((item) => item !== protocol)
  }

  function discard() {
    reset(savedModels.value)
  }

  function prepareModels(): GatewayModel[] {
    const models: GatewayModel[] = []
    const ids = new Set<string>()
    for (const group of groups.value) {
      if (!group.modelIds.length || !group.settings.providerId || !group.settings.protocols.length) {
        throw new Error(t('gateway.invalidModelRow'))
      }
      for (const entry of group.modelIds) {
        const id = entry.value.trim()
        if (!/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/.test(id)) {
          throw new Error(t('gateway.invalidModelRow'))
        }
        if (ids.has(id)) {
          throw new Error(t('gateway.duplicateModelId', { id }))
        }
        ids.add(id)
        models.push({ ...group.settings, id, protocols: [...group.settings.protocols] })
      }
    }
    return models
  }

  return { groups, dirty, providerFor, addGroup, removeGroup,
    addModelId, removeModelId, selectProvider, toggleProtocol, discard, reset, prepareModels }
}

export type GatewayModelEditor = ReturnType<typeof useGatewayModelEditor>
