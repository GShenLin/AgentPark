import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import type { ProviderInfo } from '../src/api'
import { HARNESS_NODE_TYPES, useAgentNodeCreateSchema } from '../src/composables/useAgentNodeCreateSchema'

describe('Harness node provider and model selection', () => {
  it.each(['hermes_agent_node', 'openclaw_node'])('%s creates with provider reasoning choices', typeId => {
    const fields = ref<Record<string, unknown>>({ provider_id: 'p', reasoning_effort: 'medium' })
    const schema = useAgentNodeCreateSchema({ selectedTypeId: ref(typeId), selectedNodeFields: fields,
      providers: ref([{ id: 'p', type: 'deepseek', supportmode: ['chat'], models: ['m'], model: 'm',
        features: { reasoning_effort: { supported: true, values: ['high', 'max'] } } }] as ProviderInfo[]),
      availableTools: ref([]) })
    schema.ensureCreateAgentSelections()
    expect(fields.value.reasoning_effort).toBe('high')
    fields.value.reasoning_effort = 'max'
    schema.ensureCreateAgentSelections()
    expect(fields.value.reasoning_effort).toBe('max')
  })
  for (const typeId of HARNESS_NODE_TYPES) {
    it(`${typeId} filters conversational providers and changes model with provider`, () => {
      const fields = ref<Record<string, unknown>>({ provider_id: 'first', model: 'b' })
      const providers = ref<ProviderInfo[]>([
        { id: 'first', type: 'openai', supportmode: ['chat'], models: ['a', 'b'], model: 'a' },
        { id: 'second', type: 'claude', supportmode: ['imagechat'], models: ['c'], model: 'c' },
        { id: 'image-only', type: 'openai', supportmode: ['image'], models: ['image'], model: 'image' },
      ] as ProviderInfo[])
      const schema = useAgentNodeCreateSchema({ selectedTypeId: ref(typeId), selectedNodeFields: fields,
                                               providers, availableTools: ref([]) })
      expect(schema.createProviderOptions.value).toEqual(['first', 'second'])
      expect(schema.isCreateProviderField('provider_id')).toBe(true)
      schema.ensureCreateAgentSelections()
      expect(fields.value.model).toBe('b')
      fields.value.provider_id = 'second'
      schema.ensureCreateAgentSelections()
      expect(fields.value.model).toBe('c')
    })
  }
})
