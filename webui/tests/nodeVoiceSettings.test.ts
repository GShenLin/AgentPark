import { describe, expect, it } from 'vitest'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import NodeConfigFields from '../src/components/agent-board/NodeConfigFields.vue'
import { createNodeConfigFieldSections } from '../src/components/agent-board/nodeConfigFieldGroups'

describe('node voice settings', () => {
  it('renders all three editable controls inside a closed disclosure', async () => {
    const html = await renderToString(createSSRApp(NodeConfigFields, {
      typeId: 'agent_node', providers: [], availableTools: [],
      schema: {
        voice_provider_id: { type: 'select', label: '语音 Provider', options: [{ value: 'voice-a', label: 'voice-a' }] },
        voice_model: { type: 'select', label: '语音模型', options: [] },
        voice: { type: 'select', label: '音色', options: [{ value: 'sol', label: 'Sol' }] },
      },
      fields: { voice_provider_id: 'voice-a', voice_model: 'custom-live-model', voice: 'sol' },
    }))
    const details = html.match(/<details\b([^>]*)>([\s\S]*?)<\/details>/)
    expect(details).not.toBeNull()
    expect(details![1]).not.toMatch(/\bopen(?:\s|=|$)/)
    expect(details![2]).toContain('语音设置')
    expect(details![2]).toContain('语音 Provider')
    expect(details![2]).toContain('语音模型')
    expect(details![2]).toContain('音色')
    expect(details![2].match(/<select\b/g)).toHaveLength(3)
    expect(details![2]).not.toContain('role="combobox"')
    expect(details![2]).toContain('value="custom-live-model"')
  })

  it('keeps voice fields in their own collapsed section regardless of the main Provider modes', () => {
    const keys = ['provider_id', 'voice_provider_id', 'voice_model', 'voice', 'model']
    for (const modes of [[], ['chat'], ['image_generation']]) {
      const sections = createNodeConfigFieldSections('agent_node', keys, {}, modes)
      expect(sections.find(section => section.id === 'voice')).toEqual({
        id: 'voice', label: '语音设置', collapsible: true, defaultOpen: false,
        keys: ['voice_provider_id', 'voice_model', 'voice'],
      })
      expect(sections.find(section => section.id === 'common')?.keys).toEqual(['provider_id', 'model'])
    }
  })

  it('does not create a voice section for other node types', () => {
    expect(createNodeConfigFieldSections('echo_node', ['voice'])).toEqual([
      { id: 'fields', label: '', collapsible: false, defaultOpen: true, keys: ['voice'] },
    ])
  })
})
