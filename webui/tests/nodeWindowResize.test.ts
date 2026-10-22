import { afterEach, expect, test, vi } from 'vitest'
import { createNodeWindowResize } from '../src/nodeWindowResize'
import { createNodeWindowDrag } from '../src/nodeWindowDrag'

class Handle {
  captured = false
  closest(selector: string) { return selector.includes('[data-node-window-interactive]') ? this : null }
  setPointerCapture() { this.captured = true }
  hasPointerCapture() { return this.captured }
  releasePointerCapture() { this.captured = false }
}
afterEach(() => vi.unstubAllGlobals())
function setup() {
  vi.stubGlobal('Element', Handle)
  const host = { beginResize: vi.fn(), moveResize: vi.fn(), endResize: vi.fn(), beginDrag: vi.fn(), moveDrag: vi.fn(), endDrag: vi.fn() }
  const handle = new Handle()
  const event = { button: 0, isPrimary: true, pointerId: 1, target: handle, currentTarget: handle,
    preventDefault: vi.fn(), stopPropagation: vi.fn() } as unknown as PointerEvent
  return { host, handle, event, resize: createNodeWindowResize(host), drag: createNodeWindowDrag(host) }
}

test('resize handles do not start card dragging and capture movement through release', () => {
  const { host, handle, event, resize, drag } = setup()
  drag.down(event)
  resize.down('nw', event)
  expect(host.beginDrag).not.toHaveBeenCalled()
  expect(host.beginResize).toHaveBeenCalledExactlyOnceWith('nw')
  expect(handle.captured).toBe(true)
  resize.move({ ...event, pointerId: 2 })
  expect(host.moveResize).not.toHaveBeenCalled()
  resize.move(event)
  expect(host.moveResize).toHaveBeenCalledOnce()
  resize.up(event)
  resize.up(event) // lostpointercapture after release
  resize.move(event)
  expect(host.endResize).toHaveBeenCalledOnce()
  expect(host.moveResize).toHaveBeenCalledOnce()
  expect(handle.captured).toBe(false)
})

test('blur/unmount cancellation releases capture and ignores non-primary input', () => {
  const { host, handle, event, resize } = setup()
  resize.down('e', { ...event, button: 2 })
  resize.down('e', { ...event, isPrimary: false })
  expect(host.beginResize).not.toHaveBeenCalled()
  resize.down('se', event)
  resize.cancel()
  resize.move(event)
  expect(host.endResize).toHaveBeenCalledOnce()
  expect(handle.captured).toBe(false)
  expect(host.moveResize).not.toHaveBeenCalled()
})
