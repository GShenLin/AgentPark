import { describe, expect, it } from 'vitest'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import NodeConfigFields from '../src/components/agent-board/NodeConfigFields.vue'
import { createNodeConfigFieldSections } from '../src/components/agent-board/nodeConfigFieldGroups'
import { withPersistedCapabilityState } from '../src/components/agent-board/capabilitySchemaState'

describe('node knowledge selection', () => {
  it('uses an independent capability section and the shared multiselect for multiple libraries', async () => {
    const schema = { knowledge_ids: { type: 'multiselect', label: 'Knowledge', options: [
      { value: 'library-a', label: '课件', kind: 'knowledge', description: 'embedding-model' },
      { value: 'library-b', label: '论文', kind: 'knowledge', description: 'embedding-model' },
    ] } }
    expect(createNodeConfigFieldSections('agent_node', Object.keys(schema), schema, ['chat'])).toEqual([
      { id: 'capability:knowledge_ids', label: 'Knowledge', collapsible: true, defaultOpen: false, keys: ['knowledge_ids'] },
    ])
    const html = await renderToString(createSSRApp(NodeConfigFields, {
      typeId: 'agent_node', providers: [], availableTools: [], schema,
      fields: { knowledge_ids: ['library-a', 'library-b'] },
    }))
    expect(html).toContain('课件')
    expect(html).toContain('论文')
    expect(html).toContain('library-a')
    expect(html).toContain('library-b')
  })

  it('retains unavailable selected IDs for removal without restoring a manual knowledge skill', () => {
    const result = withPersistedCapabilityState({
      knowledge_ids: { type: 'multiselect', options: [{ value: 'a', label: 'A' }] },
      skills: { type: 'multiselect', options: [] },
    }, { knowledge_ids: ['a', 'deleted'], skills: ['knowledge'] })
    expect(result.knowledge_ids.options[0].enabled).toBe(true)
    expect(result.knowledge_ids.options[1]).toMatchObject({ value: 'deleted', status: 'unavailable' })
    expect(result.skills.options).toEqual([])
  })
})
