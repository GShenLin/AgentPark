import { describe, expect, it } from 'vitest'
import type { MobileNode, ProviderInfo } from '../src/api'
import { mobileNodeTemplateRequestKey } from '../src/mobile/mobileNodeTemplateContext'

const agentNode = {
  id: 'Agent',
  type_id: 'agent_node',
} as MobileNode

const providers: ProviderInfo[] = [
  {
    id: 'tavern_deepseek_v31',
    supportmode: ['chat'],
  },
]

describe('mobile node template request context', () => {
  it('changes the request key when the complete config supplies the provider after opening', () => {
    const initialKey = mobileNodeTemplateRequestKey(true, agentNode, null, providers)
    const editorConfigKey = mobileNodeTemplateRequestKey(
      true,
      agentNode,
      { provider_id: 'tavern_deepseek_v31' },
      providers,
    )

    expect(initialKey).toBe('Agent:agent_node:')
    expect(editorConfigKey).toBe('Agent:agent_node:tavern_deepseek_v31')
    expect(editorConfigKey).not.toBe(initialKey)
  })

  it('changes the request key when provider metadata arrives after the node config', () => {
    const config = { provider_id: 'tavern_deepseek_v31' }

    expect(mobileNodeTemplateRequestKey(true, agentNode, config, [])).toBe('Agent:agent_node:')
    expect(mobileNodeTemplateRequestKey(true, agentNode, config, providers)).toBe(
      'Agent:agent_node:tavern_deepseek_v31',
    )
  })

  it('uses one stable key while the dialog is closed', () => {
    expect(mobileNodeTemplateRequestKey(false, agentNode, null, providers)).toBe('closed')
    expect(
      mobileNodeTemplateRequestKey(
        false,
        agentNode,
        { provider_id: 'tavern_deepseek_v31' },
        providers,
      ),
    ).toBe('closed')
  })
})
