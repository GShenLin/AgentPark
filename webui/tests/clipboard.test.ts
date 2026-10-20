import { afterEach, expect, it, vi } from 'vitest'
import { copyText } from '../src/clipboard'
import { useMemoryMessageExport } from '../src/composables/useMemoryMessageExport'

const state = vi.hoisted(() => ({
  graphSnapshot: { value: null }, selectedNodeId: { value: '' }, lastError: { value: null as string | null },
}))
vi.mock('../src/composables/useGlobalState', () => ({ useGlobalState: () => state }))
vi.mock('../src/api', () => ({ listFiles: vi.fn(), saveFile: vi.fn() }))
afterEach(() => { vi.unstubAllGlobals(); state.lastError.value = null })

it('copies message text through the native bridge when browser permission is denied', async () => {
  const nativeCopy = vi.fn().mockResolvedValue(undefined)
  const browserCopy = vi.fn().mockRejectedValue(new Error('Write permission denied'))
  vi.stubGlobal('window', { agentParkNodeWindow: { copyText: nativeCopy }, isSecureContext: true })
  vi.stubGlobal('navigator', { clipboard: { writeText: browserCopy } })
  await useMemoryMessageExport().copyMessageText('中文\nmessage')
  expect(nativeCopy).toHaveBeenCalledWith('中文\nmessage')
  expect(browserCopy).not.toHaveBeenCalled()
  expect(state.lastError.value).toBeNull()
})

it('reports native failures without silently switching clipboard implementations', async () => {
  const browserCopy = vi.fn()
  vi.stubGlobal('window', {
    agentParkNodeWindow: { copyText: vi.fn().mockRejectedValue(new Error('Clipboard unavailable')) },
    isSecureContext: true,
  })
  vi.stubGlobal('navigator', { clipboard: { writeText: browserCopy } })
  await useMemoryMessageExport().copyMessageText('message')
  expect(state.lastError.value).toBe('Failed to copy message: Clipboard unavailable')
  expect(browserCopy).not.toHaveBeenCalled()
})

it('uses the browser clipboard outside native windows and propagates permission failures', async () => {
  const browserCopy = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('window', { isSecureContext: true })
  vi.stubGlobal('navigator', { clipboard: { writeText: browserCopy } })
  await copyText('code block')
  expect(browserCopy).toHaveBeenCalledWith('code block')
  browserCopy.mockRejectedValue(new Error('Write permission denied'))
  await expect(copyText('denied')).rejects.toThrow('Write permission denied')
})

it('retains selection copying for browsers without a secure clipboard API', async () => {
  const textarea = { value: '', style: {}, setAttribute: vi.fn(), focus: vi.fn(),
    select: vi.fn(), setSelectionRange: vi.fn() }
  const range = {}, selection = { rangeCount: 1, getRangeAt: () => range,
    removeAllRanges: vi.fn(), addRange: vi.fn() }
  const page = { createElement: () => textarea, getSelection: () => selection,
    body: { appendChild: vi.fn(), removeChild: vi.fn() }, execCommand: vi.fn(() => true) }
  vi.stubGlobal('window', { isSecureContext: false })
  vi.stubGlobal('navigator', {})
  vi.stubGlobal('document', page)
  await copyText('text')
  expect(page.execCommand).toHaveBeenCalledWith('copy')
  expect(textarea.value).toBe('text')
  expect(page.body.removeChild).toHaveBeenCalledWith(textarea)
  expect(selection.addRange).toHaveBeenCalledWith(range)
  page.execCommand.mockReturnValue(false)
  await expect(copyText('rejected')).rejects.toThrow('Copy command was rejected')
  expect(page.body.removeChild).toHaveBeenCalledTimes(2)
})
