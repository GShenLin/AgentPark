import { expect, it } from 'vitest'
import { parseAnnotation, type AnnotationDrawing } from './screenAnnotations'
const drawing: AnnotationDrawing = { action: 'replace', frame_id: 'frame', duration_seconds: 10,
 shapes: [{ kind: 'ellipse', x: .2, y: .2, width: .3, height: .3, color: 'red' }] }

it('validates shape bounds, text lengths and extra fields', () => {
  expect(parseAnnotation(drawing)).toEqual(drawing)
  for (const data of [{ ...drawing, duration_seconds: 61 }, { ...drawing, shapes: [{ ...drawing.shapes[0], width: -1 }] },
    { ...drawing, shapes: [{ kind: 'text', x: 0, y: 0, color: 'red', text: 'x', html: true }] }, { ...drawing, action: ['replace'] }]) {
    expect(() => parseAnnotation(data)).toThrow()
  }
})

it('allows clipped ellipses and explicit coordinates without a shared frame', () => {
  const value = { ...drawing, frame_id: '', shapes: [{ ...drawing.shapes[0], x: .9 }] }
  expect(parseAnnotation(value)).toEqual(value)
})
