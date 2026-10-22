const fs = require('node:fs')
const path = require('node:path')

function validateLayout(layout) {
  if (!layout || typeof layout !== 'object' || !layout.bounds || typeof layout.bounds !== 'object'
    || !layout.bounds.card || !Number.isFinite(layout.noteHeight) || layout.noteHeight < 0 || layout.noteHeight > 248) {
    throw new Error('Invalid node window layout.')
  }
  for (const [mode, bounds] of Object.entries(layout.bounds)) {
    if (!['card', 'conversation'].includes(mode) || !bounds
      || !['x', 'y', 'width', 'height'].every(key => Number.isInteger(bounds[key]))
      || bounds.width <= 0 || bounds.height <= 0) throw new Error('Invalid node window bounds.')
  }
}

// One host process owns this store. Atomic replacement preserves the previous
// complete file if a write is interrupted; invalid data and I/O errors are explicit.
class WindowLayoutStore {
  constructor(filename) {
    this.filename = filename
    this.layouts = new Map()
    let text
    try { text = fs.readFileSync(filename, 'utf8') }
    catch (error) { if (error.code === 'ENOENT') return; throw error }
    const data = JSON.parse(text)
    if (data?.version !== 1 || !data.layouts || typeof data.layouts !== 'object' || Array.isArray(data.layouts)) {
      throw new Error('Invalid node window layout store.')
    }
    for (const [key, layout] of Object.entries(data.layouts)) {
      validateLayout(layout)
      this.layouts.set(key, layout)
    }
  }

  get(key) {
    const value = this.layouts.get(key)
    return value ? JSON.parse(JSON.stringify(value)) : undefined
  }

  save(key, layout, previousKey = key) {
    validateLayout(layout)
    const next = new Map(this.layouts)
    next.delete(previousKey)
    next.set(key, layout)
    fs.mkdirSync(path.dirname(this.filename), { recursive: true })
    fs.writeFileSync(`${this.filename}.tmp`, JSON.stringify({ version: 1, layouts: Object.fromEntries(next) }), 'utf8')
    fs.renameSync(`${this.filename}.tmp`, this.filename)
    this.layouts = next
  }
}

module.exports = { WindowLayoutStore }
