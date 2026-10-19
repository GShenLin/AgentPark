import { afterEach, expect, test, vi } from 'vitest'
import { createNodeWindowDrag } from '../src/nodeWindowDrag'

class FakeElement {
  captured = false
  constructor(private control = false) {}
  closest() { return this.control ? this : null }
  setPointerCapture() { this.captured = true }
  hasPointerCapture() { return this.captured }
  releasePointerCapture() { this.captured = false }
}
afterEach(() => vi.unstubAllGlobals())
function setup(control = false) {
  vi.stubGlobal('Element', FakeElement)
  const host = { beginDrag: vi.fn(), moveDrag: vi.fn(), endDrag: vi.fn() }
  const drag = createNodeWindowDrag(host)
  const event = { button: 0, isPrimary: true, pointerId: 1, screenX: 100, screenY: 100,
    target: new FakeElement(control), preventDefault: vi.fn() } as unknown as PointerEvent
  const click = { detail: 1, preventDefault: vi.fn(), stopImmediatePropagation: vi.fn() } as unknown as MouseEvent
  return { host, drag, event, click }
}
test('a click or tiny movement keeps node activation', () => {
  const { host, drag, event, click } = setup()
  drag.down(event)
  drag.move({ ...event, screenX: 102 })
  drag.up(event); drag.click(click)
  expect(host.moveDrag).not.toHaveBeenCalled()
  expect(click.preventDefault).not.toHaveBeenCalled()
})
test('drag moves window and suppresses the resulting click, then allows the next click', () => {
  const { host, drag, event, click } = setup()
  drag.down(event); drag.move({ ...event, screenX: 120 }); drag.up(event); drag.click(click)
  expect(host.moveDrag).toHaveBeenCalledOnce()
  expect(host.endDrag).toHaveBeenCalledOnce()
  expect(click.stopImmediatePropagation).toHaveBeenCalledOnce()
  drag.down(event); drag.up(event); drag.click(click)
  expect(click.stopImmediatePropagation).toHaveBeenCalledOnce()
})
test('buttons and other interactive controls never start a window drag', () => {
  const { host, drag, event } = setup(true)
  drag.down(event); drag.move({ ...event, screenX: 140 }); drag.up(event)
  expect(host.beginDrag).not.toHaveBeenCalled()
  expect(host.moveDrag).not.toHaveBeenCalled()
})

test('reply selection and scrolling inside the conversation never start a window drag', () => {
  const { host, drag, event } = setup()
  const closest = vi.spyOn(event.target as unknown as FakeElement, 'closest')
    .mockImplementation((...args: unknown[]) => String(args[0]).includes('[data-node-window-interactive]') ? event.target as unknown as FakeElement : null)
  drag.down(event); drag.move({ ...event, screenX: 140 }); drag.up(event)
  expect(closest).toHaveBeenCalled()
  expect(host.beginDrag).not.toHaveBeenCalled()
  expect(event.preventDefault).not.toHaveBeenCalled()
})
test('cancel ends capture and unrelated pointers cannot move the window', () => {
  const { host, drag, event } = setup()
  drag.down(event); drag.move({ ...event, pointerId: 2, screenX: 140 })
  drag.cancel(); drag.move({ ...event, screenX: 140 })
  expect(host.endDrag).toHaveBeenCalledOnce()
  expect(host.moveDrag).not.toHaveBeenCalled()
})

test('a canceled drag cannot swallow the next button click', () => {
  const { drag, event, click } = setup()
  drag.down(event); drag.move({ ...event, screenX: 140 }); drag.cancel()
  drag.down({ ...event, target: new FakeElement(true) } as unknown as PointerEvent)
  drag.click(click)
  expect(click.preventDefault).not.toHaveBeenCalled()
})
