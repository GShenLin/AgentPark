import { describe, expect, it } from 'vitest'
import {
  agentProviderModes,
  providerReasoningEffortOptions,
  reasoningEffortOptions,
} from '../src/composables/useAgentNodeCreateSchema'

describe('reasoning effort options', () => {
  it('includes explicit None and max fallback options', () => {
    expect(reasoningEffortOptions).toContainEqual({ value: 'none', label: 'None' })
    expect(reasoningEffortOptions).toContainEqual({ value: 'max', label: 'max' })
  })

  it('uses the selected provider capability values', () => {
    const options = providerReasoningEffortOptions({
      features: {
        reasoning_effort: {
          supported: true,
          values: ['none', 'low', 'high'],
        },
      },
    })

    expect(options).toEqual([
      { value: 'none', label: 'None' },
      { value: 'low', label: 'low' },
      { value: 'high', label: 'high' },
    ])
  })

  it('filters generic Agent providers by declared Agent modes', () => {
    expect(agentProviderModes({ type: 'openai', supportmode: ['chat', 'audio', 'imagechat'] })).toEqual(['chat', 'imagechat'])
  })
})
