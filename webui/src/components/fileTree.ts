import type { FileItem } from '../api'

export type FileTreeItem = FileItem & {
  children?: FileTreeItem[]
}

export function buildFileTree(items: FileItem[]): FileTreeItem[] {
  const roots: FileTreeItem[] = []
  const directories = new Map<string, FileTreeItem>()

  for (const item of items) {
    const normalizedPath = String(item.path || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
    if (!normalizedPath) continue

    const segments = normalizedPath.split('/').filter(Boolean)
    let siblings = roots
    let currentPath = ''

    for (let index = 0; index < segments.length - 1; index += 1) {
      const segment = segments[index]
      if (!segment) continue
      currentPath = currentPath ? `${currentPath}/${segment}` : segment
      let directory = directories.get(currentPath)
      if (!directory) {
        directory = { name: segment, path: currentPath, type: 'dir', children: [] }
        directories.set(currentPath, directory)
        siblings.push(directory)
      }
      siblings = directory.children ?? []
    }

    const name = segments[segments.length - 1]
    if (!name) continue
    if (!siblings.some((entry) => entry.path === normalizedPath)) {
      siblings.push({ ...item, name, path: normalizedPath })
    }
  }

  return roots
}
