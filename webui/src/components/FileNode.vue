<script setup lang="ts">
import { computed, ref } from 'vue'
import { listFiles, type FileItem } from '../api'
import FileNode from './FileNode.vue'

const props = defineProps<{
  name: string
  path: string
  type: 'dir' | 'file'
  level?: number
}>()

const emit = defineEmits<{
  (e: 'file-selected', file: FileItem): void
  (e: 'folder-dblclick', path: string): void
  (e: 'item-contextmenu', payload: { item: FileItem; x: number; y: number }): void
}>()

const isOpen = ref(false)
const children = ref<FileItem[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)

const isDir = computed(() => props.type === 'dir')
const level = computed(() => Number(props.level || 0))
const rowPaddingLeft = computed(() => `${level.value * 14 + 8}px`)

const sortedChildren = computed(() => {
  return [...children.value].sort((a, b) => {
    if (a.type !== b.type) {
      return a.type === 'dir' ? -1 : 1
    }
    return String(a.name || '').localeCompare(String(b.name || ''))
  })
})

function emitFileSelected() {
  emit('file-selected', { name: props.name, path: props.path, type: props.type })
}

function handleRowClick() {
  if (isDir.value) {
    void toggle()
    return
  }
  emitFileSelected()
}

function handleRowDblClick() {
  if (!isDir.value) return
  emit('folder-dblclick', props.path)
}

async function toggle() {
  if (!isDir.value) return
  isOpen.value = !isOpen.value

  if (!isOpen.value) return
  if (children.value.length > 0) return

  isLoading.value = true
  error.value = null
  try {
    const res = await listFiles(props.path)
    children.value = Array.isArray(res.files) ? res.files : []
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    isLoading.value = false
  }
}

function onDragStart(event: DragEvent) {
  if (!event.dataTransfer) return
  event.dataTransfer.setData('text/plain', props.path)
  event.dataTransfer.setData(
    'application/x-agentpark-file',
    JSON.stringify({
      name: props.name,
      path: props.path,
      type: props.type,
    }),
  )
  event.dataTransfer.effectAllowed = 'copy'
}

function onContextMenu(event: MouseEvent) {
  emit('item-contextmenu', {
    item: {
      name: props.name,
      path: props.path,
      type: props.type,
    },
    x: event.clientX,
    y: event.clientY,
  })
}
</script>

<template>
  <div class="file-node">
    <div
      class="file-row"
      :class="{ 'is-dir': isDir, 'is-open': isOpen }"
      :style="{ paddingLeft: rowPaddingLeft }"
      :draggable="props.type === 'file'"
      @click="handleRowClick"
      @dblclick.stop="handleRowDblClick"
      @dragstart="onDragStart"
      @contextmenu.prevent.stop="onContextMenu"
    >
      <button
        v-if="isDir"
        class="expander"
        type="button"
        @click.stop="toggle"
      >
        {{ isOpen ? '-' : '+' }}
      </button>
      <span v-else class="expander-placeholder"></span>

      <span class="type-tag" :class="{ dir: isDir, file: !isDir }">
        {{ isDir ? 'DIR' : 'FILE' }}
      </span>
      <span class="name" :title="path">{{ name }}</span>
      <span v-if="isLoading" class="loading">loading...</span>
    </div>

    <div v-if="error" class="error" :style="{ paddingLeft: `${(level + 1) * 14 + 8}px` }">{{ error }}</div>

    <div v-if="isOpen && isDir" class="children">
      <FileNode
        v-for="child in sortedChildren"
        :key="child.path"
        v-bind="child"
        :level="level + 1"
        @file-selected="(f) => emit('file-selected', f)"
        @folder-dblclick="(p) => emit('folder-dblclick', p)"
        @item-contextmenu="(payload) => emit('item-contextmenu', payload)"
      />
      <div
        v-if="sortedChildren.length === 0 && !isLoading"
        class="empty"
        :style="{ paddingLeft: `${(level + 1) * 14 + 8}px` }"
      >
        (empty)
      </div>
    </div>
  </div>
</template>

<style scoped>
.file-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 3px;
  padding-bottom: 3px;
  cursor: pointer;
  color: rgba(226, 232, 240, 0.9);
  border-radius: 6px;
}

.file-row:hover {
  background: rgba(51, 65, 85, 0.5);
}

.expander,
.expander-placeholder {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.expander {
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 4px;
  background: rgba(15, 23, 42, 0.7);
  color: rgba(226, 232, 240, 0.95);
  font-size: 11px;
  line-height: 16px;
  padding: 0;
}

.type-tag {
  font-size: 10px;
  letter-spacing: 0.4px;
  border-radius: 4px;
  padding: 1px 4px;
  border: 1px solid rgba(148, 163, 184, 0.4);
}

.type-tag.dir {
  background: rgba(30, 64, 175, 0.2);
  border-color: rgba(96, 165, 250, 0.45);
}

.type-tag.file {
  background: rgba(30, 41, 59, 0.45);
}

.name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.loading {
  margin-left: auto;
  font-size: 10px;
  color: rgba(148, 163, 184, 0.85);
}

.error {
  color: #fca5a5;
  font-size: 11px;
  padding-top: 2px;
  padding-bottom: 2px;
}

.empty {
  color: rgba(148, 163, 184, 0.7);
  font-size: 11px;
  padding-top: 3px;
  padding-bottom: 3px;
}
</style>
