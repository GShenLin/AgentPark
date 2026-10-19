export type AnnotationColor = 'red' | 'yellow' | 'cyan' | 'green' | 'white'
type Position = { x: number; y: number; color: AnnotationColor }
export type AnnotationShape = Position & (
  { kind: 'ellipse'; width: number; height: number } |
  { kind: 'arrow'; to_x: number; to_y: number } |
  { kind: 'text'; text: string })
export type AnnotationDrawing = { action: 'replace' | 'clear'; frame_id: string; shapes: AnnotationShape[]; duration_seconds: number }
export type AnnotationDisplay = { id: string; label: string; width: number; height: number; x: number; y: number }

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const unit = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
export function parseAnnotation(value: unknown): AnnotationDrawing {
  if (!object(value) || Object.keys(value).some(key => !['action', 'frame_id', 'shapes', 'duration_seconds'].includes(key))
      || typeof value.action !== 'string' || !['replace', 'clear'].includes(value.action) || typeof value.frame_id !== 'string' || value.frame_id.length > 80
      || !Number.isInteger(value.duration_seconds) || Number(value.duration_seconds) < 1 || Number(value.duration_seconds) > 60
      || !Array.isArray(value.shapes) || value.shapes.length > 12) throw new Error('屏幕标注参数无效。')
  if (value.action === 'replace' ? !value.shapes.length : value.shapes.length) throw new Error('屏幕标注缺少图形或包含无效图形。')
  for (const shape of value.shapes) {
    if (!object(shape) || !unit(shape.x) || !unit(shape.y) || typeof shape.color !== 'string' || !['red', 'yellow', 'cyan', 'green', 'white'].includes(shape.color)) throw new Error('标注坐标或颜色无效。')
    let fields = ['kind', 'x', 'y', 'color']
    if (shape.kind === 'ellipse') {
      fields = [...fields, 'width', 'height']
      if (!unit(shape.width) || !unit(shape.height) || shape.width <= 0 || shape.height <= 0) throw new Error('标注圆圈尺寸必须大于0且不超过1。')
    } else if (shape.kind === 'arrow') {
      fields = [...fields, 'to_x', 'to_y']
      if (!unit(shape.to_x) || !unit(shape.to_y)) throw new Error('箭头坐标无效。')
    } else if (shape.kind === 'text') {
      fields = [...fields, 'text']
      if (typeof shape.text !== 'string' || !shape.text.length || shape.text.length > 100) throw new Error('标注文字须为1–100个字符。')
    } else throw new Error('不支持的标注图形。')
    if (Object.keys(shape).some(key => !fields.includes(key))) throw new Error('标注图形包含无效字段。')
  }
  return value as AnnotationDrawing
}

export function parseDisplays(value: unknown): AnnotationDisplay[] {
  if (!Array.isArray(value) || !value.length || value.some(item => !object(item)
      || typeof item.id !== 'string' || !item.id || typeof item.label !== 'string'
      || !['width', 'height', 'x', 'y'].every(key => typeof item[key] === 'number' && Number.isFinite(item[key]))
      || Number(item.width) <= 0 || Number(item.height) <= 0)) throw new Error('桌面宿主未返回有效显示器。')
  return value as AnnotationDisplay[]
}
