import { describe, expect, it } from 'vitest'
import type { GatewayModel, GatewayProvider, GatewaySettings } from '../src/gatewayApi'
import { useGatewayModelEditor } from '../src/components/settings/gatewayModelEditor'

const providers: GatewayProvider[] = [
  { id: 'text', model: 'upstream-text', protocol: 'openai_chat', protocols: ['responses', 'chat_completions', 'messages'], authProvider: 'openai', accounts: [], kind: 'provider' },
  { id: 'image', model: 'upstream-image', protocol: 'images', protocols: ['images_generations', 'images_edits'], authProvider: 'openai', accounts: [], kind: 'provider' },
]

function model(id: string): GatewayModel {
  return { id, providerId: 'text', accountId: '', protocols: ['responses', 'messages'], enabled: true }
}

function settings(models: GatewayModel[]): GatewaySettings {
  return { models, providers, enabled: true, requireApiKey: true, keys: [], sourceErrors: [] }
}

describe('Provider model ID list editor', () => {
  it('loads multiple IDs for the same Provider in one group', () => {
    const editor = useGatewayModelEditor([model('alpha'), model('beta')], () => providers)
    expect(editor.dirty.value).toBe(false)
    expect(editor.groups.value).toHaveLength(1)
    expect(editor.groups.value[0]!.modelIds.map((entry) => entry.value)).toEqual(['alpha', 'beta'])
    expect(editor.groups.value[0]!.settings.providerId).toBe('text')
  })

  it('adds three IDs under one Provider, saves shared settings, and reloads one group', async () => {
    const initial = [model('alpha'), model('beta')]
    const editor = useGatewayModelEditor(initial, () => providers)
    const group = editor.groups.value[0]!
    editor.addModelId(group)
    group.modelIds[2]!.value = ' gamma '
    group.settings.accountId = 'abcdef123456'
    editor.toggleProtocol(group.settings, 'responses', false)
    expect(initial).toEqual([model('alpha'), model('beta')])
    expect(editor.dirty.value).toBe(true)
    const result = settings(editor.prepareModels())
    editor.reset(result.models)
    const expected = ['alpha', 'beta', 'gamma'].map((id) => ({ ...model(id), accountId: 'abcdef123456', protocols: ['messages'] }))
    expect(editor.prepareModels()).toEqual(expected)
    expect(result?.models).toEqual(expected)
    expect(editor.dirty.value).toBe(false)
    const reloaded = useGatewayModelEditor(result!.models, () => providers)
    expect(reloaded.groups.value).toHaveLength(1)
    expect(reloaded.groups.value[0]!.modelIds.map((entry) => entry.value)).toEqual(['alpha', 'beta', 'gamma'])
  })

  it('keeps different Provider configurations independent', async () => {
    const editor = useGatewayModelEditor([model('alpha'), model('beta')], () => providers)
    editor.addGroup()
    const image = editor.groups.value[1]!
    image.settings.providerId = 'image'
    image.settings.accountId = 'abcdef123456'
    editor.selectProvider(image.settings)
    expect(image.settings.accountId).toBe('')
    expect(image.settings.protocols).toEqual(['images_generations', 'images_edits'])
    image.modelIds[0]!.value = 'image-a'
    editor.addModelId(image)
    image.modelIds[1]!.value = 'image-b'
    image.settings.enabled = false
    expect(editor.prepareModels()).toEqual([
      model('alpha'), model('beta'),
      ...['image-a', 'image-b'].map((id) => ({ id, providerId: 'image', accountId: '', protocols: ['images_generations', 'images_edits'], enabled: false })),
    ])
    expect(editor.groups.value).toHaveLength(2)
  })

  it('does not merge different account, protocol, or enabled settings for the same Provider', () => {
    const editor = useGatewayModelEditor([
      model('alpha'), { ...model('beta'), accountId: 'abcdef123456' },
      { ...model('gamma'), protocols: ['responses'] }, { ...model('delta'), enabled: false },
    ], () => providers)
    expect(editor.groups.value).toHaveLength(4)
    expect(editor.dirty.value).toBe(false)
  })

  it('renames and removes an ID without removing siblings or copying the wrong value', async () => {
    const editor = useGatewayModelEditor([model('alpha'), model('beta'), model('gamma')], () => providers)
    const group = editor.groups.value[0]!
    const retainedKey = group.modelIds[2]!.key
    group.modelIds[0]!.value = 'renamed'
    editor.removeModelId(group, group.modelIds[1]!.key)
    expect(group.modelIds[1]!.key).toBe(retainedKey)
    expect(editor.prepareModels()).toEqual([model('renamed'), model('gamma')])
    editor.removeGroup(editor.groups.value[0]!.key)
    expect(editor.prepareModels()).toEqual([])
  })

  it.each([false, true])('rejects duplicate IDs within or across Provider groups (across=%s)', async (across) => {
    const second = { ...model(' alpha '), providerId: across ? 'image' : 'text' }
    const editor = useGatewayModelEditor([model('alpha'), second], () => providers)
    expect(() => editor.prepareModels()).toThrow('duplicated')
  })

  it.each(['', 'bad id'])('rejects invalid ID %j without dropping that entry', async (id) => {
    const editor = useGatewayModelEditor([model('alpha'), model(id)], () => providers)
    expect(() => editor.prepareModels()).toThrow()
    expect(editor.groups.value[0]!.modelIds).toHaveLength(2)
  })

  it('rejects a Provider group with no model IDs', async () => {
    const editor = useGatewayModelEditor([model('alpha')], () => providers)
    const group = editor.groups.value[0]!
    editor.removeModelId(group, group.modelIds[0]!.key)
    expect(editor.dirty.value).toBe(true)
    expect(() => editor.prepareModels()).toThrow()
  })

  it('discards changes to model IDs and Provider groups', () => {
    const editor = useGatewayModelEditor([model('alpha'), model('beta')], () => providers)
    const group = editor.groups.value[0]!
    group.modelIds[0]!.value = 'changed'
    editor.removeModelId(group, group.modelIds[1]!.key)
    editor.addGroup()
    editor.discard()
    expect(editor.groups.value).toHaveLength(1)
    expect(editor.groups.value[0]!.modelIds.map((entry) => entry.value)).toEqual(['alpha', 'beta'])
    expect(editor.dirty.value).toBe(false)
  })
})
