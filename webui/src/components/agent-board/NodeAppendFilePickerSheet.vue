<script setup lang="ts">
import { computed } from 'vue'
import type { FileItem, NodeInstanceFile } from '../../api'
import FileExplorer from '../FileExplorer.vue'
import { buildFileTree } from '../fileTree'

const props = defineProps<{
  files: NodeInstanceFile[]
  loading: boolean
  saving: boolean
}>()

const selectedPaths = defineModel<string[]>('selectedPaths', { required: true })
const customPath = defineModel<string>('customPath', { required: true })

const emit = defineEmits<{
  close: []
  confirm: []
}>()

const treeItems = computed(() => buildFileTree(props.files.map((file): FileItem => ({
  name: file.name,
  path: file.path,
  type: 'file',
}))))

function removePath(path: string) {
  selectedPaths.value = selectedPaths.value.filter((item) => item !== path)
}
</script>

<template>
  <Teleport to="body">
    <div class="append-file-picker-backdrop" @click.self="emit('close')">
      <section class="append-file-picker" role="dialog" aria-modal="true" aria-label="选择节点文件">
        <div class="append-file-picker-head">
          <div>
            <div class="append-file-picker-title">选择节点文件（多选）</div>
            <div class="append-file-picker-subtitle">一个 AppendFile 可加载多个文件；不存在的文件会单独跳过。</div>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭文件选择" @click="emit('close')">×</button>
        </div>

        <label class="append-file-picker-input-wrap">
          <span>添加尚不存在的文件名</span>
          <input
            v-model="customPath"
            type="text"
            inputmode="text"
            autocomplete="off"
            placeholder="例如 Memory.md 或 notes/context.md"
          />
        </label>

        <div v-if="selectedPaths.length" class="append-file-picker-selected">
          <span class="append-file-picker-selected-title">已选择 {{ selectedPaths.length }} 个</span>
          <div class="append-file-picker-chips">
            <button v-for="path in selectedPaths" :key="path" type="button" class="append-file-picker-chip" @click="removePath(path)">
              <span>{{ path }}</span><b aria-hidden="true">×</b>
            </button>
          </div>
        </div>

        <div class="append-file-picker-list">
          <div v-if="loading" class="empty-hint">正在读取节点目录...</div>
          <FileExplorer
            v-else-if="treeItems.length"
            v-model:selected-paths="selectedPaths"
            :items="treeItems"
            :show-header="false"
            :context-menu-enabled="false"
            selectable
          />
          <div v-else class="empty-hint">节点目录中暂无文件，可直接填写文件名。</div>
        </div>

        <div class="append-file-picker-actions">
          <button class="mini-btn" type="button" :disabled="saving" @click="emit('close')">取消</button>
          <button class="mini-btn primary" type="button" :disabled="saving || (!selectedPaths.length && !customPath.trim())" @click="emit('confirm')">
            {{ saving ? '保存中...' : '确定' }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.append-file-picker-backdrop { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; background: rgba(2, 6, 23, 0.72); padding: 20px; }
.append-file-picker { width: min(720px, 100%); max-height: min(78vh, 680px); display: flex; flex-direction: column; gap: 12px; border: 1px solid rgba(148, 163, 184, 0.24); border-radius: 12px; background: #08111f; box-shadow: 0 18px 40px rgba(2, 6, 23, 0.42); padding: 14px; }
.append-file-picker-head, .append-file-picker-actions { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.append-file-picker-title { color: #f8fafc; font-size: 15px; font-weight: 700; }
.append-file-picker-subtitle { margin-top: 3px; color: rgba(148, 163, 184, 0.9); font-size: 11px; }
.append-file-picker-input-wrap { display: flex; flex-direction: column; gap: 5px; color: rgba(203, 213, 225, 0.9); font-size: 11px; }
.append-file-picker-input-wrap input { width: 100%; box-sizing: border-box; border: 1px solid rgba(148, 163, 184, 0.3); border-radius: 8px; background: rgba(15, 23, 42, 0.92); color: #f8fafc; padding: 9px 10px; font-size: 13px; }
.append-file-picker-selected { display: flex; flex-direction: column; gap: 6px; }
.append-file-picker-selected-title { color: rgba(203, 213, 225, 0.9); font-size: 11px; }
.append-file-picker-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.append-file-picker-chip { max-width: 100%; display: flex; align-items: center; gap: 7px; border: 1px solid rgba(45, 212, 191, 0.4); border-radius: 999px; background: rgba(13, 148, 136, 0.16); color: #ccfbf1; padding: 5px 9px; }
.append-file-picker-chip span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.append-file-picker-chip b { flex: 0 0 auto; color: #99f6e4; font-size: 14px; }
.append-file-picker-list { min-height: 160px; flex: 1 1 280px; overflow: hidden; border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 9px; background: rgba(15, 23, 42, 0.42); }
.append-file-picker-list > .empty-hint { padding: 14px 10px; }
.append-file-picker-list :deep(.file-list) { overscroll-behavior: contain; -webkit-overflow-scrolling: touch; padding: 6px; }
.append-file-picker-list :deep(button) { backdrop-filter: none; -webkit-backdrop-filter: none; transform: none; transition: background-color 0.12s ease, border-color 0.12s ease, color 0.12s ease; }
.append-file-picker-actions { justify-content: flex-end; border-top: 1px solid rgba(148, 163, 184, 0.16); padding-top: 12px; }
.empty-hint { margin-top: 2px; color: rgba(148, 163, 184, 0.84); font-size: 11px; }
.mini-btn, .icon-btn { border: 1px solid rgba(148, 163, 184, 0.26); border-radius: 8px; background: rgba(15, 23, 42, 0.92); color: #f8fafc; cursor: pointer; padding: 6px 9px; font-size: 12px; white-space: nowrap; }
.mini-btn.primary { border-color: rgba(45, 212, 191, 0.35); background: rgba(13, 148, 136, 0.2); }
.icon-btn { width: 30px; height: 30px; padding: 0; font-size: 18px; }
.mini-btn:disabled { cursor: default; opacity: 0.55; }

@media (max-width: 760px) {
  .append-file-picker-backdrop { align-items: flex-end; padding: 0; }
  .append-file-picker { width: 100%; border-width: 1px 0 0; border-radius: 0; box-shadow: 0 -18px 40px rgba(2, 6, 23, 0.42); }
}
</style>
