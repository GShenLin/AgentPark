import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getGatewaySettings, updateGatewaySettings, type GatewaySettings } from '../src/gatewayApi'
import { useGatewaySettingsEditor } from '../src/components/settings/gatewaySettingsEditor'

vi.mock('../src/gatewayApi', () => ({ getGatewaySettings: vi.fn(), updateGatewaySettings: vi.fn() }))

function snapshot(): GatewaySettings {
  return {
    enabled: true, requireApiKey: true, keys: [], sourceErrors: [],
    providers: [{ id: 'shared', model: 'default', protocol: 'openai_chat', protocols: ['responses'], authProvider: 'openai', accounts: [], kind: 'provider' }],
    models: ['model-a', 'model-b'].map((id) => ({ id, providerId: 'shared', accountId: '', protocols: ['responses'], enabled: true })),
  }
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(getGatewaySettings).mockResolvedValue(snapshot())
  vi.mocked(updateGatewaySettings).mockImplementation(async (payload) => ({ ...snapshot(), ...payload }))
})

describe('one gateway toolbar save', () => {
  it('saves option changes and newly added model IDs in one request and reloads both', async () => {
    const editor = useGatewaySettingsEditor()
    await editor.load()
    expect(editor.dirty.value).toBe(false)
    editor.enabled.value = false
    editor.requireApiKey.value = false
    const group = editor.models.groups.value[0]!
    editor.models.addModelId(group)
    group.modelIds[2]!.value = ' model-c '
    group.settings.accountId = 'abcdef123456'
    expect(editor.dirty.value).toBe(true)
    expect(editor.settings.value?.models).toHaveLength(2)
    expect(await editor.save()).toBe(true)
    expect(updateGatewaySettings).toHaveBeenCalledExactlyOnceWith({
      enabled: false, requireApiKey: false,
      models: ['model-a', 'model-b', 'model-c'].map((id) => ({ id, providerId: 'shared', accountId: 'abcdef123456', protocols: ['responses'], enabled: true })),
    })
    expect(editor.dirty.value).toBe(false)
    expect(editor.status.value).toContain('saved')
    vi.mocked(getGatewaySettings).mockResolvedValue(editor.settings.value!)
    const reopened = useGatewaySettingsEditor()
    await reopened.load()
    expect(reopened.enabled.value).toBe(false)
    expect(reopened.requireApiKey.value).toBe(false)
    expect(reopened.models.groups.value[0]!.modelIds.map((entry) => entry.value)).toEqual(['model-a', 'model-b', 'model-c'])
  })

  it('saves a model-only change even when both switches are unchanged', async () => {
    const editor = useGatewaySettingsEditor()
    await editor.load()
    editor.models.groups.value[0]!.modelIds[1]!.value = 'replacement-model'
    expect(editor.dirty.value).toBe(true)
    expect(await editor.save()).toBe(true)
    expect(vi.mocked(updateGatewaySettings).mock.calls[0]![0].models[1]!.id).toBe('replacement-model')
  })

  it('does not save switches when a model ID is invalid and keeps all drafts for correction', async () => {
    const editor = useGatewaySettingsEditor()
    await editor.load()
    editor.enabled.value = false
    editor.models.addModelId(editor.models.groups.value[0]!)
    expect(await editor.save()).toBe(false)
    expect(updateGatewaySettings).not.toHaveBeenCalled()
    expect(editor.error.value).not.toBe('')
    expect(editor.settings.value?.enabled).toBe(true)
    expect(editor.enabled.value).toBe(false)
    expect(editor.models.groups.value[0]!.modelIds).toHaveLength(3)
    expect(editor.dirty.value).toBe(true)
  })

  it('retains switches and model drafts after backend rejection, then retries successfully', async () => {
    const editor = useGatewaySettingsEditor()
    await editor.load()
    editor.requireApiKey.value = false
    editor.models.groups.value[0]!.modelIds[1]!.value = 'new-model'
    vi.mocked(updateGatewaySettings).mockRejectedValueOnce(new Error('Account unavailable'))
    expect(await editor.save()).toBe(false)
    expect(editor.error.value).toBe('Account unavailable')
    expect(editor.saving.value).toBe(false)
    expect(editor.dirty.value).toBe(true)
    expect(editor.requireApiKey.value).toBe(false)
    expect(editor.models.groups.value[0]!.modelIds[1]!.value).toBe('new-model')
    expect(await editor.save()).toBe(true)
    expect(editor.error.value).toBe('')
    expect(editor.dirty.value).toBe(false)
  })

  it('discards all option and model changes together', async () => {
    const editor = useGatewaySettingsEditor()
    await editor.load()
    editor.enabled.value = false
    editor.models.removeGroup(editor.models.groups.value[0]!.key)
    editor.discard()
    expect(editor.enabled.value).toBe(true)
    expect(editor.models.prepareModels()).toEqual(snapshot().models)
    expect(editor.dirty.value).toBe(false)
  })

  it('blocks duplicate saves while the unified request is pending', async () => {
    const editor = useGatewaySettingsEditor()
    await editor.load()
    let finish!: (value: GatewaySettings) => void
    vi.mocked(updateGatewaySettings).mockReturnValue(new Promise((resolve) => { finish = resolve }))
    editor.enabled.value = false
    const pending = editor.save()
    expect(editor.saving.value).toBe(true)
    expect(await editor.save()).toBe(false)
    expect(updateGatewaySettings).toHaveBeenCalledTimes(1)
    finish({ ...snapshot(), enabled: false })
    expect(await pending).toBe(true)
    expect(editor.saving.value).toBe(false)
  })
})
