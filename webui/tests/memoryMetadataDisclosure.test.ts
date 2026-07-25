import { createSSRApp, h, type Component } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it, vi } from 'vitest'
import type { MessageEnvelope } from '../src/api'

vi.mock('../src/components/MemoryFileDiffDialog.vue', () => ({
  default: { render: () => null },
}))
vi.mock('../src/components/ImageLightbox.vue', () => ({
  default: { render: () => null },
}))

import MemoryMessageParts from '../src/components/MemoryMessageParts.vue'
import MemoryMetadataDisclosure from '../src/components/MemoryMetadataDisclosure.vue'
import MobileMessageText from '../src/mobile/MobileMessageText.vue'

const persistedMessage = {
  id: 'assistant-committed',
  role: 'assistant',
  created_at: '2026-07-24T12:00:00Z',
  parts: [
    { type: 'text', text: 'Committed response' },
    {
      type: 'structured',
      data: {
        kind: 'response_metadata',
        display_placement: 'associated',
        display_created_at: '2026-07-24T12:00:01Z',
        provider_requests: [{ provider: 'test-provider' }],
      },
    },
  ],
} as unknown as MessageEnvelope

async function renderComponent(
  component: Component,
  props: Record<string, unknown> = {},
  slots?: Record<string, () => unknown>,
) {
  return renderToString(createSSRApp({
    render: () => h(component, props, slots),
  }))
}

function expectCollapsedMetadata(html: string) {
  expect(html).toContain('class="metadata-disclosure"')
  expect(html).toContain('aria-expanded="false"')
  expect(html).not.toContain('metadata-disclosure-content')
}

describe('persisted associated metadata disclosure', () => {
  it('is collapsed after the desktop history handoff', async () => {
    const html = await renderComponent(MemoryMessageParts, {
      message: persistedMessage,
      markdownPreview: true,
    })

    expectCollapsedMetadata(html)
  })

  it('is collapsed after the mobile history handoff', async () => {
    const html = await renderComponent(MobileMessageText, {
      message: persistedMessage,
    })

    expectCollapsedMetadata(html)
  })

  it('keeps explicit expansion as an opt-in instead of changing disclosure state semantics', async () => {
    const collapsed = await renderComponent(
      MemoryMetadataDisclosure,
      {},
      { default: () => h('span', 'metadata-body') },
    )
    const expanded = await renderComponent(
      MemoryMetadataDisclosure,
      { defaultExpanded: true },
      { default: () => h('span', 'metadata-body') },
    )

    expectCollapsedMetadata(collapsed)
    expect(expanded).toContain('class="metadata-disclosure expanded"')
    expect(expanded).toContain('aria-expanded="true"')
    expect(expanded).toContain('metadata-body')
  })
})
