<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { listFiles, type FileItem } from '../api'

const props = withDefaults(defineProps<{
  open: boolean
  initialPath?: string
  title?: string
}>(), {
  initialPath: '',
  title: '选择工作路径',
})

const emit = defineEmits<{
  close: []
  select: [path: string]
  error: [message: string]
}>()

const currentPath = ref('')
const directories = ref<FileItem[]>([])
const loading = ref(false)
const loadError = ref('')
let requestId = 0

const parentPath = computed(() => getParentDirectory(currentPath.value))
const canGoUp = computed(() => {
  const current = String(currentPath.value || '').trim()
  const parent = String(parentPath.value || '').trim()
  return !!parent && parent !== current
})

function getParentDirectory(value: string) {
  const current = String(value || '').trim()
  if (!current) return ''

  if (/^[A-Za-z]:[\\/]?$/.test(current)) {
    return current.endsWith('\\') || current.endsWith('/') ? current : `${current}\\`
  }
  if (current === '/' || current === '\\') return current

  const withoutTrailingSeparator = current.replace(/[\\/]+$/, '')
  if (withoutTrailingSeparator.startsWith('\\\\')) {
    const uncParts = withoutTrailingSeparator.slice(2).split(/[\\/]+/).filter(Boolean)
    if (uncParts.length <= 2) return current
  }

  const lastSeparator = Math.max(
    withoutTrailingSeparator.lastIndexOf('/'),
    withoutTrailingSeparator.lastIndexOf('\\'),
  )
  if (lastSeparator < 0) return ''
  if (lastSeparator === 0) return withoutTrailingSeparator[0]

  const parent = withoutTrailingSeparator.slice(0, lastSeparator)
  return /^[A-Za-z]:$/.test(parent) ? `${parent}\\` : parent
}

async function loadDirectory(path: string) {
  const activeRequestId = ++requestId
  loading.value = true
  loadError.value = ''
  try {
    const response = await listFiles(String(path || '').trim())
    if (activeRequestId !== requestId) return
    currentPath.value = String(response.current_path || '').trim()
    directories.value = (Array.isArray(response.files) ? response.files : [])
      .filter((item) => item.type === 'dir')
  } catch (error: any) {
    if (activeRequestId !== requestId) return
    directories.value = []
    loadError.value = String(error?.message || error)
  } finally {
    if (activeRequestId === requestId) loading.value = false
  }
}

function enterDirectory(path: string) {
  void loadDirectory(path)
}

function goUp() {
  if (!canGoUp.value) return
  void loadDirectory(parentPath.value || '')
}

function refresh() {
  void loadDirectory(currentPath.value)
}

function selectCurrentDirectory() {
  const selectedPath = String(currentPath.value || '').trim()
  if (!selectedPath) return
  emit('select', selectedPath)
}

watch(
  () => props.open,
  (open) => {
    if (!open) {
      requestId += 1
      return
    }
    void loadDirectory(String(props.initialPath || '').trim())
  },
  { immediate: true },
)

watch(loadError, (message) => {
  if (message) emit('error', message)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="folder-picker-backdrop" @mousedown.self="emit('close')">
      <section class="folder-picker-dialog" role="dialog" aria-modal="true" :aria-label="title">
        <header class="folder-picker-head">
          <div class="folder-picker-heading">
            <div class="folder-picker-title">{{ title }}</div>
            <div class="folder-picker-current" :title="currentPath">{{ currentPath || '加载路径中...' }}</div>
          </div>
          <button class="folder-picker-close" type="button" aria-label="关闭目录选择" @click="emit('close')">x</button>
        </header>

        <div class="folder-picker-toolbar">
          <button class="folder-picker-tool" type="button" :disabled="loading || !canGoUp" @click="goUp">
            ↑ 上一级
          </button>
          <button class="folder-picker-tool" type="button" :disabled="loading" @click="refresh">刷新</button>
        </div>

        <div class="folder-picker-body">
          <div v-if="loading" class="folder-picker-status">正在读取文件夹...</div>
          <div v-else-if="loadError" class="folder-picker-status error">
            <span>{{ loadError }}</span>
            <button class="folder-picker-retry" type="button" @click="refresh">重试</button>
          </div>
          <div v-else-if="directories.length === 0" class="folder-picker-status">当前路径下没有子文件夹。</div>
          <template v-else>
            <button
              v-for="directory in directories"
              :key="directory.path"
              class="folder-picker-directory"
              type="button"
              :title="directory.path"
              @click="enterDirectory(directory.path)"
            >
              <span class="folder-picker-icon">▰</span>
              <span class="folder-picker-name">{{ directory.name }}</span>
              <span class="folder-picker-enter">›</span>
            </button>
          </template>
        </div>

        <footer class="folder-picker-actions">
          <button class="folder-picker-btn" type="button" @click="emit('close')">取消</button>
          <button
            class="folder-picker-btn primary"
            type="button"
            :disabled="loading || !!loadError || !currentPath"
            @click="selectCurrentDirectory"
          >
            选择当前文件夹
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.folder-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(2, 6, 23, 0.78);
}

.folder-picker-dialog {
  width: min(560px, 100%);
  max-height: min(76vh, 680px);
  max-height: min(76dvh, 680px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(56, 189, 248, 0.32);
  border-radius: 14px;
  background: #08111f;
  color: rgba(226, 232, 240, 0.96);
  box-shadow: 0 24px 72px rgba(0, 0, 0, 0.48);
}

/* Avoid Android Chrome dropping composited button layers while this list scrolls. */
.folder-picker-dialog button {
  -webkit-appearance: none;
  appearance: none;
  -webkit-backdrop-filter: none;
  backdrop-filter: none;
  box-shadow: none;
  transform: none;
  transition: border-color 120ms ease, background-color 120ms ease, opacity 120ms ease;
}

.folder-picker-dialog button:hover,
.folder-picker-dialog button:active {
  box-shadow: none;
  transform: none;
}

.folder-picker-head,
.folder-picker-toolbar,
.folder-picker-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
}

.folder-picker-head {
  justify-content: space-between;
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
}

.folder-picker-heading {
  min-width: 0;
}

.folder-picker-title {
  font-size: 16px;
  font-weight: 750;
}

.folder-picker-current {
  margin-top: 4px;
  overflow: hidden;
  color: rgba(148, 163, 184, 0.92);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-picker-close {
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 9px;
  background: rgba(15, 23, 42, 0.78);
  color: rgba(226, 232, 240, 0.94);
  cursor: pointer;
}

.folder-picker-toolbar {
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.folder-picker-tool,
.folder-picker-btn,
.folder-picker-retry {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 9px;
  background: rgba(15, 23, 42, 0.78);
  color: rgba(226, 232, 240, 0.94);
  cursor: pointer;
}

.folder-picker-tool {
  min-height: 34px;
  padding: 6px 11px;
  font-size: 12px;
}

.folder-picker-body {
  flex: 1 1 auto;
  min-height: 180px;
  overflow: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 12px 14px;
}

.folder-picker-directory {
  width: 100%;
  min-height: 48px;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 8px;
  padding: 9px 11px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.64);
  color: rgba(226, 232, 240, 0.96);
  text-align: left;
  cursor: pointer;
}

.folder-picker-directory:hover,
.folder-picker-directory:active {
  border-color: rgba(56, 189, 248, 0.64);
  background: rgba(14, 116, 144, 0.2);
}

.folder-picker-icon {
  color: rgba(56, 189, 248, 0.9);
  font-size: 15px;
}

.folder-picker-name {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-picker-enter {
  color: rgba(148, 163, 184, 0.92);
  font-size: 22px;
}

.folder-picker-status {
  min-height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 18px;
  color: rgba(148, 163, 184, 0.94);
  font-size: 13px;
  text-align: center;
}

.folder-picker-status.error {
  flex-direction: column;
  color: rgba(252, 165, 165, 0.96);
}

.folder-picker-retry {
  padding: 6px 12px;
}

.folder-picker-actions {
  justify-content: flex-end;
  padding-bottom: calc(12px + env(safe-area-inset-bottom));
  border-top: 1px solid rgba(148, 163, 184, 0.16);
}

.folder-picker-btn {
  min-height: 38px;
  padding: 7px 14px;
  font-size: 13px;
}

.folder-picker-btn.primary {
  border-color: rgba(56, 189, 248, 0.7);
  background: rgba(14, 116, 144, 0.44);
}

.folder-picker-tool:disabled,
.folder-picker-btn:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

@media (max-width: 640px) {
  .folder-picker-backdrop {
    align-items: flex-end;
    padding: 0;
  }

  .folder-picker-dialog {
    width: 100%;
    height: min(82vh, 720px);
    height: min(82dvh, 720px);
    max-height: none;
    border-right: 0;
    border-bottom: 0;
    border-left: 0;
    border-radius: 14px 14px 0 0;
  }

  .folder-picker-body {
    min-height: 0;
  }

  .folder-picker-directory {
    flex: 0 0 auto;
  }
}
</style>
