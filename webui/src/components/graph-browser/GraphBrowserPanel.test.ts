import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { describe, expect, it, vi } from 'vitest'
import GraphBrowserPanel from '../GraphBrowserPanel.vue'

vi.mock('./GraphContents.vue', () => ({ default: {
  props: ['graph'], setup: (props: { graph: { id: string } }) => () => h('section', { 'data-graph-contents': props.graph.id }, 'Groups and nodes'),
} }))

describe('Graph browser rendering', () => {
  it('renders only the current Graph’s contents beneath its own Graph row', async () => {
    const html = await renderToString(createSSRApp(GraphBrowserPanel, {
      graphId: 'graph-b', graphNameInput: 'B', graphWorkingPathInput: '', graphLoading: false,
      graphMemoryClearingId: '', graphs: [{ id: 'graph-a', name: 'A' }, { id: 'graph-b', name: 'B' }],
      graphProfiles: [], selectedGraphProfileId: '',
    }))
    expect(html).not.toContain('data-graph-contents="graph-a"')
    expect(html).toContain('data-graph-contents="graph-b"')
    expect(html.indexOf('data-graph-contents="graph-b"')).toBeGreaterThan(html.indexOf('graph-current'))
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain('aria-expanded="true"')
    expect(html).not.toContain('class="group-list"')
  })
})
