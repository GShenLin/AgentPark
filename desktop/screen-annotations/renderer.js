const canvas = document.getElementById('canvas')
const colors = { red: '#ff505e', yellow: '#ffe45e', cyan: '#31e7ff', green: '#65f59a', white: '#ffffff' }
function element(tag, attrs) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag)
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value))
  canvas.appendChild(node)
  return node
}
const nextPaint = () => new Promise(resolve => requestAnimationFrame(resolve))
async function confirmViewport(width, height) {
  const deadline = performance.now() + 2000
  let matchingPaints = 0
  while (matchingPaints < 2) {
    await nextPaint()
    if (performance.now() >= deadline) throw new Error('标注画布尺寸未与显示器同步。')
    matchingPaints = window.innerWidth === width && window.innerHeight === height ? matchingPaints + 1 : 0
  }
}
window.annotations.receive(async ({ id, drawing, viewport }) => {
  try {
    canvas.replaceChildren()
    const { width, height } = viewport
    if (!Number.isInteger(width) || width <= 0 || !Number.isInteger(height) || height <= 0) {
      throw new Error('Invalid annotation viewport.')
    }
    // setBounds and Chromium resize are asynchronous across processes. Use the
    // selected display's explicit DIP geometry, never a stale innerWidth.
    canvas.setAttribute('viewBox', `0 0 ${width} ${height}`)
    canvas.setAttribute('preserveAspectRatio', 'none')
    for (const shape of drawing.shapes) {
      if (!Object.hasOwn(colors, shape.color)) throw new Error('Invalid annotation color.')
      const color = colors[shape.color], x = shape.x * width, y = shape.y * height
      if (shape.kind === 'ellipse') {
        element('ellipse', { cx: x + shape.width * width / 2, cy: y + shape.height * height / 2,
          rx: shape.width * width / 2, ry: shape.height * height / 2, stroke: color })
      } else if (shape.kind === 'arrow') {
        const tx = shape.to_x * width, ty = shape.to_y * height, angle = Math.atan2(ty - y, tx - x), size = 15
        element('path', { stroke: color, d: `M ${x} ${y} L ${tx} ${ty} M ${tx - size * Math.cos(angle - 0.5)} ${ty - size * Math.sin(angle - 0.5)} L ${tx} ${ty} L ${tx - size * Math.cos(angle + 0.5)} ${ty - size * Math.sin(angle + 0.5)}` })
      } else if (shape.kind === 'text') {
        const font = 24, lines = shape.text.split('\n')
        const node = element('text', { x, y, 'dominant-baseline': 'text-before-edge', fill: color, 'font-size': font })
        for (let index = 0; index < lines.length; index++) {
          const line = document.createElementNS('http://www.w3.org/2000/svg', 'tspan')
          line.setAttribute('x', String(x)); line.setAttribute('dy', index ? '1.2em' : '0')
          line.textContent = lines[index]; node.appendChild(line)
        }
        const box = node.getBBox()
        if (box.width > width - x - 8) {
          node.setAttribute('textLength', String(Math.max(1, width - x - 8)))
          node.setAttribute('lengthAdjust', 'spacingAndGlyphs')
        }
      } else throw new Error('Unknown annotation shape.')
    }
    await confirmViewport(width, height)
    window.annotations.painted(id)
  } catch (error) { canvas.replaceChildren(); window.annotations.painted(id, error.message) }
})
