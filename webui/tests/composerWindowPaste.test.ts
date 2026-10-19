import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { createRenderer, ref } from 'vue'
import { useComposerWindowPaste } from '../src/composables/useComposerWindowPaste'
import { useMessageAttachments } from '../src/composables/useMessageAttachments'
import type { MessageAttachment } from '../src/composables/messageAttachments'

const upload = vi.hoisted(() => vi.fn())
vi.mock('../src/uploadApi', () => ({ uploadFiles: upload }))
vi.mock('../src/composables/droppedPaths', () => ({ resolveDroppedPaths: vi.fn() }))

class ElementStub { constructor(readonly editable = false) {} closest() { return this.editable ? this : null } }
class TextareaStub extends ElementStub {}
const renderer = createRenderer<object, object>({
  patchProp() {}, insert() {}, remove() {}, createElement: () => ({}),
  createText: () => ({}), createComment: () => ({}), setText() {}, setElementText() {},
  parentNode: () => null, nextSibling: () => null,
})
const cleanups: Array<() => void> = []
beforeEach(() => {
  vi.stubGlobal('window', new EventTarget())
  vi.stubGlobal('document', { querySelector: vi.fn(() => null) })
  vi.stubGlobal('Element', ElementStub)
  vi.stubGlobal('HTMLTextAreaElement', TextareaStub)
  upload.mockReset().mockImplementation(async (files: File[]) => ({
    files: files.map(file => ({ name: file.name, path: `/uploads/${file.name}`, kind: file.type.startsWith('image/') ? 'image' : 'file' })),
  }))
})
afterEach(() => { cleanups.splice(0).forEach(fn => fn()); vi.unstubAllGlobals() })

function setup() {
  const text = ref('existing draft\n'), attachments = ref<MessageAttachment[]>([]), active = ref(true), error = vi.fn()
  const app = renderer.createApp({ setup() {
    const shared = useMessageAttachments({ text, attachments, context: () => 'graph:node', onError: error })
    useComposerWindowPaste({ text, active: () => active.value, paste: shared.paste })
    return () => null
  } })
  app.mount({})
  cleanups.push(() => app.unmount())
  return { text, attachments, active, error, app }
}
function paste(files: File[] = [], text = '', target: unknown = null, prevented = false) {
  const event = new Event('paste', { cancelable: true }) as ClipboardEvent
  Object.defineProperty(event, 'clipboardData', { value: {
    types: files.length ? ['Files', 'text/plain'] : ['text/plain'], files,
    items: files.map(file => ({ kind: 'file', getAsFile: () => file })),
    getData: (type: string) => type === 'text/plain' ? text : '',
  } })
  if (target) Object.defineProperty(event, 'target', { value: target })
  if (prevented) event.preventDefault()
  window.dispatchEvent(event)
  return event
}
const flushUpload = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }

test.each([['image.png', 'image/png'], ['notes.pdf', 'application/pdf']])('unfocused paste adds %s to the unsent attachments', async (name, mime) => {
  const h = setup(), file = new File(['data'], name, { type: mime })
  const event = paste([file])
  expect(event.defaultPrevented).toBe(true)
  await flushUpload()
  expect(upload).toHaveBeenCalledExactlyOnceWith([file], 'message-composer')
  expect(h.attachments.value).toMatchObject([{ name, path: `/uploads/${name}` }])
  expect(h.text.value).toBe('existing draft\n')
})
test('mixed text and files inserts text once and retains the existing draft', async () => {
  const h = setup()
  paste([new File(['png'], 'shot.png', { type: 'image/png' })], 'caption')
  await flushUpload()
  expect(h.text.value).toBe('existing draft\ncaption')
  expect(h.attachments.value).toHaveLength(1)
})
test('plain text is appended to the unsent draft without any upload', () => {
  const h = setup()
  expect(paste([], 'pasted\ntext').defaultPrevented).toBe(true)
  expect(h.text.value).toBe('existing draft\npasted\ntext')
  expect(upload).not.toHaveBeenCalled()
})
test('focused editors and already-handled paste are left to their existing handlers', () => {
  const h = setup(), file = new File(['x'], 'shot.png')
  paste([file], 'text', new ElementStub(true))
  paste([file], 'text', null, true)
  expect(upload).not.toHaveBeenCalled()
  expect(h.text.value).toBe('existing draft\n')
})
test('collapsed chat, settings and modal dialogs do not receive draft paste', () => {
  const h = setup()
  h.active.value = false
  paste([new File(['x'], 'shot.png')], 'hidden')
  h.active.value = true
  vi.mocked(document.querySelector).mockReturnValue({} as Element)
  paste([new File(['x'], 'shot.png')], 'modal')
  expect(upload).not.toHaveBeenCalled()
  expect(h.text.value).toBe('existing draft\n')
})
test('upload failure reports an error and leaves the draft intact', async () => {
  const h = setup()
  upload.mockRejectedValueOnce(new Error('Upload failed'))
  paste([new File(['x'], 'shot.png')])
  await flushUpload()
  expect(h.error).toHaveBeenCalledWith('Upload failed')
  expect(h.attachments.value).toEqual([])
  expect(h.text.value).toBe('existing draft\n')
})
test('unmount removes the window paste listener', () => {
  setup().app.unmount()
  paste([new File(['x'], 'shot.png')])
  expect(upload).not.toHaveBeenCalled()
})
