<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { deleteFilePath, listFiles, renameFilePath, saveFile, type FileItem } from '../api'
import FileNode from './FileNode.vue'

const props = withDefaults(defineProps<{
  rootPath?: string
}>(), {
  rootPath: '',
})

const emit = defineEmits<{
  (e: 'file-selected', file: FileItem): void
}>()

const files = ref<FileItem[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const rootPath = ref(String(props.rootPath || '').trim())
const searchQuery = ref('')

const menuOpen = ref(false)
const menuX = ref(0)
const menuY = ref(0)
const menuTarget = ref<FileItem | null>(null)
const isMenuTargetDir = computed(() => menuTarget.value?.type === 'dir')

const sortedFiles = computed(() => {
  return [...files.value].sort((a, b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
    return String(a.name || '').localeCompare(String(b.name || ''))
  })
})

const currentPathLabel = computed(() => {
  const path = String(rootPath.value || '').trim()
  return path || '(root)'
})

function baseName(path: string) {
  const normalized = String(path || '').replace(/[\\/]+$/, '')
  const idx = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'))
  if (idx < 0) return normalized
  return normalized.slice(idx + 1)
}

function dirName(path: string) {
  const normalized = String(path || '').replace(/[\\/]+$/, '')
  const idx = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'))
  if (idx < 0) return ''
  if (idx === 0) return normalized.slice(0, 1)
  const dir = normalized.slice(0, idx)
  return dir.endsWith(':') ? `${dir}\\` : dir
}

function joinPath(dir: string, name: string) {
  const cleanDir = String(dir || '').trim()
  const cleanName = String(name || '').trim()
  if (!cleanDir) return cleanName
  if (!cleanName) return cleanDir
  const isWin = /[a-zA-Z]:\\/.test(cleanDir) || cleanDir.includes('\\')
  const sep = isWin ? '\\' : '/'
  const dirNoTail = cleanDir.replace(/[\\/]+$/, '')
  const nameNoHead = cleanName.replace(/^[\\/]+/, '')
  return `${dirNoTail}${sep}${nameNoHead}`
}

function openMenu(x: number, y: number, target: FileItem | null) {
  menuTarget.value = target
  menuX.value = x
  menuY.value = y
  menuOpen.value = true
}

function closeMenu() {
  menuOpen.value = false
  menuTarget.value = null
}

function onGlobalPointerDown() {
  if (!menuOpen.value) return
  closeMenu()
}

function onGlobalKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeMenu()
  }
}

async function refresh() {
  isLoading.value = true
  error.value = null
  try {
    const res = await listFiles(rootPath.value || '', searchQuery.value)
    files.value = Array.isArray(res.files) ? res.files : []
    if (!searchQuery.value) {
      rootPath.value = String(res.current_path || rootPath.value || '')
    }
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    isLoading.value = false
  }
}

function goUp() {
  const current = String(rootPath.value || '').trim()
  if (!current) return

  const normalized = current.replace(/[\\/]$/, '')
  const lastSep = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'))

  if (lastSep > 0) {
    const next = normalized.slice(0, lastSep)
    rootPath.value = next.endsWith(':') ? `${next}\\` : next
    void refresh()
    return
  }

  if (lastSep === 0) {
    rootPath.value = '/'
    void refresh()
  }
}

function clearSearch() {
  if (!searchQuery.value) return
  searchQuery.value = ''
  void refresh()
}

function onFolderDblClick(path: string) {
  rootPath.value = path
  searchQuery.value = ''
  void refresh()
}

function onBlankContextMenu(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (target?.closest('.file-row')) return
  openMenu(event.clientX, event.clientY, null)
}

function onItemContextMenu(payload: { item: FileItem; x: number; y: number }) {
  openMenu(payload.x, payload.y, payload.item)
}

async function createFileAtFolder(folderPath: string) {
  const currentFolder = String(folderPath || '').trim()
  if (!currentFolder) return
  const fileName = window.prompt('New file name', 'new_file.txt')
  const cleanName = String(fileName || '').trim()
  if (!cleanName) return

  const filePath = joinPath(currentFolder, cleanName)
  try {
    await saveFile(filePath, '')
    await refresh()
  } catch (e: any) {
    error.value = String(e?.message || e)
  }
}

async function createFileInCurrentFolder() {
  closeMenu()
  await createFileAtFolder(rootPath.value)
}

async function createFileInTargetFolder() {
  const target = menuTarget.value
  closeMenu()
  if (!target || target.type !== 'dir') return
  await createFileAtFolder(target.path)
}

async function renameTarget() {
  const target = menuTarget.value
  closeMenu()
  if (!target) return

  const oldPath = String(target.path || '')
  const parent = dirName(oldPath)
  const defaultName = baseName(oldPath)
  const inputName = window.prompt('Rename to', defaultName)
  const nextName = String(inputName || '').trim()
  if (!nextName || nextName === defaultName) return

  const newPath = joinPath(parent, nextName)
  try {
    await renameFilePath(oldPath, newPath)
    await refresh()
  } catch (e: any) {
    error.value = String(e?.message || e)
  }
}

async function deleteTarget() {
  const target = menuTarget.value
  closeMenu()
  if (!target) return

  const label = target.type === 'dir' ? 'folder' : 'file'
  const ok = window.confirm(`Delete ${label}: ${target.name}?`)
  if (!ok) return

  try {
    await deleteFilePath(target.path, true)
    await refresh()
  } catch (e: any) {
    error.value = String(e?.message || e)
  }
}

onMounted(() => {
  void refresh()
  window.addEventListener('pointerdown', onGlobalPointerDown)
  window.addEventListener('keydown', onGlobalKeyDown)
})

onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', onGlobalPointerDown)
  window.removeEventListener('keydown', onGlobalKeyDown)
})

watch(
  () => props.rootPath,
  (nextPath) => {
    const path = String(nextPath || '').trim()
    if (path === String(rootPath.value || '').trim()) return
    rootPath.value = path
    searchQuery.value = ''
    void refresh()
  },
)
</script>

<template>
  <div class="file-explorer">
    <div class="header-group">
      <div class="toolbar">
        <button class="tool-btn" type="button" @click="goUp">Up</button>
        <button class="tool-btn" type="button" @click="refresh">Refresh</button>
        <button class="tool-btn" type="button" :disabled="!searchQuery" @click="clearSearch">Clear Search</button>
      </div>

      <label class="input-row">
        <span class="input-label">Path</span>
        <input
          v-model="rootPath"
          class="path-input"
          placeholder="Enter path and press Enter"
          @keyup.enter="refresh"
        />
      </label>

      <label class="input-row">
        <span class="input-label">Filter</span>
        <input
          v-model="searchQuery"
          class="search-input"
          placeholder="Filter file name"
          @keyup.enter="refresh"
        />
      </label>

      <div class="path-hint" :title="currentPathLabel">Current: {{ currentPathLabel }}</div>
    </div>

    <div class="file-list" @contextmenu.prevent="onBlankContextMenu">
      <div v-if="isLoading" class="loading-state">Loading files...</div>
      <div v-else-if="error" class="error-state">{{ error }}</div>
      <template v-else>
        <FileNode
          v-for="file in sortedFiles"
          :key="file.path"
          v-bind="file"
          :level="0"
          @file-selected="(f) => emit('file-selected', f)"
          @folder-dblclick="onFolderDblClick"
          @item-contextmenu="onItemContextMenu"
        />
        <div v-if="sortedFiles.length === 0" class="empty-state">No files found</div>
      </template>

      <div
        v-if="menuOpen"
        class="context-menu"
        :style="{ left: `${menuX}px`, top: `${menuY}px` }"
        @pointerdown.stop
      >
        <template v-if="!menuTarget">
          <button class="menu-item" type="button" @click="createFileInCurrentFolder">Create File</button>
        </template>
        <template v-else>
          <div class="menu-title">{{ menuTarget.name }}</div>
          <button v-if="isMenuTargetDir" class="menu-item" type="button" @click="createFileInTargetFolder">
            Create File Here
          </button>
          <button class="menu-item" type="button" @click="renameTarget">Rename</button>
          <button class="menu-item danger" type="button" @click="deleteTarget">Delete</button>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.file-explorer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  color: rgba(255, 255, 255, 0.92);
}

.header-group {
  display: flex;
  flex-direction: column;
  padding: 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  background: rgba(2, 6, 23, 0.55);
  gap: 8px;
}

.toolbar {
  display: flex;
  gap: 6px;
}

.tool-btn {
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(15, 23, 42, 0.75);
  color: rgba(226, 232, 240, 0.95);
  border-radius: 8px;
  font-size: 11px;
  padding: 4px 8px;
}

.tool-btn:disabled {
  opacity: 0.45;
}

.input-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.input-label {
  width: 42px;
  flex-shrink: 0;
  font-size: 11px;
  color: rgba(148, 163, 184, 0.95);
}

.path-input,
.search-input {
  flex: 1;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(15, 23, 42, 0.55);
  color: rgba(226, 232, 240, 0.96);
  border-radius: 8px;
  padding: 6px 8px;
  font-size: 12px;
  outline: none;
}

.path-input:focus,
.search-input:focus {
  border-color: rgba(56, 189, 248, 0.7);
}

.path-hint {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.88);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-list {
  position: relative;
  flex: 1;
  overflow-y: auto;
  padding: 6px 8px 10px;
}

.loading-state,
.empty-state {
  padding: 18px 8px;
  text-align: center;
  color: rgba(148, 163, 184, 0.85);
  font-size: 12px;
}

.error-state {
  padding: 14px 8px;
  color: #fca5a5;
  font-size: 12px;
  white-space: pre-wrap;
}

.context-menu {
  position: fixed;
  min-width: 150px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(15, 23, 42, 0.96);
  border-radius: 10px;
  padding: 6px;
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.45);
  z-index: 2500;
}

.menu-title {
  font-size: 11px;
  color: rgba(148, 163, 184, 0.9);
  padding: 4px 8px 6px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.menu-item {
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: transparent;
  color: rgba(226, 232, 240, 0.95);
  border-radius: 8px;
  padding: 6px 8px;
  font-size: 12px;
}

.menu-item:hover {
  background: rgba(51, 65, 85, 0.7);
}

.menu-item.danger:hover {
  background: rgba(127, 29, 29, 0.7);
  color: rgba(254, 226, 226, 0.98);
}
</style>
