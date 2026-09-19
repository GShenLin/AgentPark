import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { NodeInstanceConfig } from '../src/api'

const apiMocks = vi.hoisted(() => ({
  getNodeInstanceConfig: vi.fn(),
}))

vi.mock('../src/api', () => apiMocks)

import { loadMobileNodeEditorConfig } from '../src/mobile/mobileNodeEditorConfig'

function nodeConfig(overrides: Partial<NodeInstanceConfig> = {}): NodeInstanceConfig {
  return {
    graph_id: 'default',
    node_id: 'agent-1',
    type_id: 'agent_node',
    provider_id: 'openai',
    thinking: true,
    reasoning_effort: 'high',
    ...overrides,
  }
}

describe('mobile node editor config source', () => {
  beforeEach(() => {
    apiMocks.getNodeInstanceConfig.mockReset()
  })

  it('loads and returns the complete editor config for the selected node', async () => {
    const config = nodeConfig()
    apiMocks.getNodeInstanceConfig.mockResolvedValue({ node: config, version: 3 })

    await expect(loadMobileNodeEditorConfig('agent-1', 'default')).resolves.toBe(config)
    expect(apiMocks.getNodeInstanceConfig).toHaveBeenCalledWith('agent-1', 'default')
  })

  it.each([
    nodeConfig({ node_id: 'other-node' }),
    nodeConfig({ graph_id: 'other-graph' }),
    nodeConfig({ graph_id: undefined }),
  ])('rejects a response that does not belong to the requested graph and node', async (config) => {
    apiMocks.getNodeInstanceConfig.mockResolvedValue({ node: config, version: 3 })

    await expect(loadMobileNodeEditorConfig('agent-1', 'default')).rejects.toThrow(
      'Node config response identity mismatch',
    )
  })
})
