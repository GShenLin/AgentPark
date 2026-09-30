import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { compile, NodeTypes, parse as parseTemplate, type ElementNode, type TemplateChildNode } from '@vue/compiler-dom'
import { parse } from '@vue/compiler-sfc'
import { describe, expect, it, vi } from 'vitest'
import type { LiveActivityBlock, MessageEnvelope } from '../src/api'
import { resolveLiveCompletionHandoff } from '../src/liveCompletionHandoff'

vi.mock('../src/components/MemoryFileDiffDialog.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/components/ImageLightbox.vue', () => ({ default: { render: () => null } }))
import MemoryContentView from '../src/components/MemoryContentView.vue'
import MobileLiveMessage from '../src/mobile/MobileLiveMessage.vue'

type LiveState = {
  liveMessage: string
  thinkingMessage: string
  activityMessage: string
  activityBlocks: LiveActivityBlock[]
}
const empty: LiveState = { liveMessage: '', thinkingMessage: '', activityMessage: '', activityBlocks: [] }
const tool: LiveActivityBlock = {
  id: 'tool-1', type: 'tool_call', label: 'inspect_device', status: 'running',
  call_id: 'call-1', arguments: { path: 'work/file.txt' }, text: 'tool-output',
}
function user(running: boolean): MessageEnvelope {
  return {
    id: 'u1', role: 'user', parts: [{ type: 'text', text: 'question' }],
    turn_summary: { turn_id: 'u1', revision: 'v1', running, item_count: 1, tool_count: 1, has_metadata: true },
  }
}

async function desktop(state: LiveState, messages: MessageEnvelope[], markdownPreview = true) {
  const loadTurnDetails = vi.fn()
  const html = await renderToString(createSSRApp({ render: () => h(MemoryContentView, {
    mode: 'agent', memoryText: '', messages, ...state, nodeId: 'node', graphId: 'graph',
    markdownPreview, wordWrap: true, showLineNumbers: false, agentImages: [], renderedMarkdown: '',
    graphNameInput: '', graphWorkingPathInput: '', graphLoading: false, graphMemoryClearingId: '',
    graphNodesLoadingId: '', expandedGraphId: '', graphs: [], graphNodesById: {}, graphProfiles: [],
    selectedGraphProfileId: '', interactiveSessionId: '', interactiveInputText: '',
    interactiveInputDisabled: false, interactiveSending: false, loadTurnDetails,
  }) }))
  expect(loadTurnDetails).not.toHaveBeenCalled()
  expect(html).not.toContain('progress-group-list')
  return html
}

function findLive(nodes: TemplateChildNode[]): ElementNode | undefined {
  for (const node of nodes) {
    if (node.type !== NodeTypes.ELEMENT) continue
    if (node.tag === 'MobileLiveMessage') return node
    const found = findLive(node.children)
    if (found) return found
  }
}

// Compile the actual mobile workspace binding, not a copied test-only template.
// This detects removal, incorrect channel wiring and running-turn suppression
// without booting unrelated connection, recorder and navigation services in SSR.
function mobileRender() {
  const source = readFileSync(new URL('../src/mobile/MobileWorkspace.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  expect(descriptor.scriptSetup?.content).toContain("import MobileLiveMessage from './MobileLiveMessage.vue'")
  const live = findLive(parseTemplate(descriptor.template!.content).children)
  expect(live, 'MobileWorkspace must mount Live output').toBeDefined()
  const { code } = compile(live!.loc.source, { mode: 'function', prefixIdentifiers: true })
  return new Function('Vue', code)(Vue)
}

async function mobile(state: LiveState, messages: MessageEnvelope[]) {
  return renderToString(createSSRApp({
    components: { MobileLiveMessage },
    setup: () => ({ ...state, messages, workspace: {
      selectedPc: { value: { id: 'local' } },
      selectedGraph: { value: { id: 'graph' } },
      selectedNode: { value: { id: 'node' } },
    } }),
    render: mobileRender(),
  }))
}

for (const [name, render] of [['desktop', desktop], ['mobile', mobile]] as const) {
  describe(`${name} Live output`, () => {
    it.each([false, true])('renders every channel independently with running=%s', async running => {
      for (const [state, text] of [
        [{ ...empty, liveMessage: 'answer-stream' }, 'answer-stream'],
        [{ ...empty, thinkingMessage: 'thinking-stream' }, 'thinking-stream'],
        [{ ...empty, activityMessage: '**activity-stream**' }, '<strong>activity-stream</strong>'],
        [{ ...empty, activityBlocks: [tool] }, 'inspect_device'],
      ] as const) {
        const html = await render(state, [user(running)])
        expect(html).toContain(text)
        expect(html).toContain('streaming')
      }
    })

    it('renders combined streams and passes node/graph IDs to running tool controls', async () => {
      const html = await render({ liveMessage: 'answer-stream', thinkingMessage: 'thinking-stream',
        activityMessage: 'activity-stream', activityBlocks: [tool] }, [user(true)])
      for (const text of ['answer-stream', 'thinking-stream', 'activity-stream', 'tool-output', 'work/file.txt', 'Stop']) {
        expect(html).toContain(text)
      }
    })

    it('renders Live before a persisted user turn arrives', async () => {
      expect(await render({ ...empty, liveMessage: 'early-stream' }, [])).toContain('early-stream')
    })

    it('does not render an empty Live panel even while a turn is running', async () => {
      const html = await render(empty, [user(true)])
      expect(html).not.toMatch(/class="(?:mobile-)?live-message"/)
      expect(html).not.toContain('streaming')
    })

    it('keeps pending output visible, then removes Live after the final message is committed', async () => {
      const state = { ...empty, liveMessage: 'completed-answer' }
      expect(resolveLiveCompletionHandoff([user(true)], state.liveMessage, 'trace-1').status).toBe('pending')
      expect(await render(state, [user(true)])).toContain('completed-answer')
      const messages: MessageEnvelope[] = [user(false), {
        id: 'a1', role: 'assistant', trace_id: 'trace-1', parts: [{ type: 'text', text: state.liveMessage }],
      }]
      expect(resolveLiveCompletionHandoff(messages, state.liveMessage, 'trace-1').status).toBe('committed')
      // Both workspace controllers clear the stream on a committed handoff.
      expect(await render(empty, messages)).not.toMatch(/class="(?:mobile-)?live-message"/)
    })
  })
}

it('preserves desktop raw activity and live text wrapping', async () => {
  const html = await desktop({ ...empty, liveMessage: 'raw-answer', activityMessage: '**raw-activity**' }, [user(true)], false)
  expect(html).toContain('**raw-activity**')
  expect(html).not.toContain('<strong>raw-activity</strong>')
  expect(html).toMatch(/class="(?=[^"]*\blog-text\b)(?=[^"]*\bwrapped\b)[^"]*"/)
})
