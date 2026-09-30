import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { describe, expect, it } from 'vitest'
import ConversationWindow from './ConversationWindow.vue'

async function renderWindow(floating: boolean) {
  const context: { teleports?: Record<string, string> } = {}
  const html = await renderToString(createSSRApp({
    __scopeId: 'data-v-workspace-test',
    render: () => h(ConversationWindow, { floating, label: 'Graphs', class: 'right' },
      { default: () => h('div', { class: 'contents' }, 'Graph contents') }),
  }), context)
  return html + (context.teleports?.['#app'] ?? '')
}

describe('ConversationWindow layout ownership', () => {
  it('owns docked layout inside the Teleport boundary without a parent scope', async () => {
    const html = await renderWindow(false)
    const aside = html.match(/<aside\b[^>]*>/)?.[0] ?? ''
    // Parent scoped selectors cannot reach the actual aside through Teleport.
    expect(aside).not.toContain('data-v-workspace-test')
    expect(aside).toContain('is-docked')
    expect(html).toContain('Graph contents')
    expect(aside).not.toContain('aria-modal')
  })

  it('keeps the floating conversation modal separate from docked layout', async () => {
    const html = await renderWindow(true)
    const aside = html.match(/<aside\b[^>]*>/)?.[0] ?? ''
    expect(aside).toContain('is-floating')
    expect(aside).not.toContain('is-docked')
    expect(aside).toContain('aria-modal="true"')
    expect(html).toContain('conversation-backdrop')
  })
})
