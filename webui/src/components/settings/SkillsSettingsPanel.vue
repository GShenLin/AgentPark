<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import SkillFolderTree from './SkillFolderTree.vue'
import SkillDetailDialog from './SkillDetailDialog.vue'
import SkillOrganizeDialog from './SkillOrganizeDialog.vue'
import SkillSourcesSettings from './SkillSourcesSettings.vue'
import { listSkills, operateSkill, skillView, type SkillCatalog, type SkillEntry, type SkillSource } from '../../skillsApi'

const catalog = ref<SkillCatalog | null>(null)
const selectedRoot = ref('')
const current = ref('')
const query = ref('')
const loading = ref(false)
const error = ref('')
const message = ref('')
const detail = ref<SkillEntry | null>(null)
const editing = ref<{ action: 'create_folder' | 'move' | 'delete'; entry?: SkillEntry; rootId: string } | null>(null)
const sources = computed(() => catalog.value?.sources || [])
const source = computed(() => sources.value.find(item => item.id === selectedRoot.value))
const editingSource = computed(() => sources.value.find(item => item.id === editing.value?.rootId))
const allEntries = computed(() => sources.value.flatMap(item => item.entries))
const entries = computed(() => source.value?.entries || allEntries.value)
const visible = computed(() => {
  if (query.value.trim()) return skillView(allEntries.value, '', query.value)
  if (!source.value) return allEntries.value.filter(entry => entry.kind === 'skill')
  return skillView(entries.value, current.value, '')
})
const folders = computed(() => visible.value.filter(entry => entry.kind === 'folder'))
const skills = computed(() => visible.value.filter(entry => entry.kind === 'skill'))
const total = computed(() => allEntries.value.filter(entry => entry.kind === 'skill').length)
const trash = computed(() => sources.value.flatMap(item => item.trash.map(record => ({ ...record, rootId: item.id, label: item.label }))))
const breadcrumbs = computed(() => current.value.split('/').filter(Boolean).map((name, index, parts) => ({ name, path: parts.slice(0, index + 1).join('/') })))
const currentEntry = computed(() => source.value?.entries.find(entry => entry.path === current.value))
const count = (item: SkillSource) => item.entries.filter(entry => entry.kind === 'skill').length
const sourceLabel = (id: string) => sources.value.find(item => item.id === id)?.label || ''
function navigate(path: string, rootId = selectedRoot.value) { selectedRoot.value = rootId; current.value = path; query.value = '' }
function organize(action: 'create_folder' | 'move' | 'delete', entry?: SkillEntry) {
  const rootId = entry?.root_id || source.value?.id || sources.value[0]?.id
  if (rootId) editing.value = { action, entry, rootId }
}
async function refresh() {
  loading.value = true; error.value = ''
  try {
    catalog.value = await listSkills()
    if (selectedRoot.value && !source.value) navigate('', '')
    if (current.value && !source.value?.entries.some(entry => entry.path === current.value)) current.value = ''
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}
async function saved() {
  const action = editing.value?.action
  editing.value = null
  message.value = action === 'delete' ? '已移入回收区，可在页面底部恢复。' : '已保存，Skill 列表已更新。'
  await refresh()
}
async function restore(rootId: string, id: string) {
  loading.value = true; error.value = ''; message.value = ''
  try { await operateSkill({ root_id: rootId, action: 'restore', trash_id: id }); message.value = '已恢复到原来的文件夹。'; await refresh() }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}
onMounted(refresh)
</script>

<template>
  <section class="skills-panel" :aria-busy="loading">
    <header class="skills-head">
      <div><h2>我的 Skills <span class="skill-total">{{ total }}</span></h2><p>项目、用户与自定义目录中的能力，都可以在这里查看和整理。</p></div>
      <div class="skill-actions"><ActionButton :disabled="loading || !sources.length" @click="organize('create_folder')">新建文件夹</ActionButton><ActionButton :disabled="loading" @click="refresh">{{ loading ? '刷新中…' : '刷新' }}</ActionButton></div>
    </header>
    <SkillSourcesSettings :sources="sources" @changed="refresh" />
    <div class="skill-search"><FormTextInput v-model="query" type="search" placeholder="搜索所有 Skill 的名称、用途或文件夹…" aria-label="搜索 Skills" /><span class="skill-muted">搜索所有来源与层级</span></div>
    <p v-if="error" class="skill-error" role="alert">{{ error }}</p><p v-if="message" class="skill-status" role="status">{{ message }}</p>
    <p v-if="catalog?.usage_error" class="skill-error" role="alert">引用检查失败，修复以下配置后才能移动或删除：{{ catalog.usage_error }}</p>
    <div class="skill-browser">
      <aside class="skill-sidebar">
        <strong>加载来源</strong>
        <button class="skill-root" :class="{ selected: !selectedRoot }" @click="navigate('', '')"><span>全部 Skills</span><small>{{ total }}</small></button>
        <template v-for="item in sources" :key="item.id">
          <button class="skill-root" :title="item.path" :class="{ selected: selectedRoot === item.id && !current }" @click="navigate('', item.id)"><span>{{ item.label }}</span><small>{{ count(item) }}</small></button>
          <SkillFolderTree v-if="selectedRoot === item.id" :entries="item.entries" :current="current" @navigate="navigate($event, item.id)" />
        </template>
      </aside>
      <main class="skill-content">
        <nav class="skill-breadcrumbs" aria-label="Skill 目录路径">
          <button @click="navigate('', '')">全部 Skills</button>
          <template v-if="source"><span>/</span><button @click="navigate('')">{{ source.label }}</button></template>
          <template v-for="crumb in breadcrumbs" :key="crumb.path"><span>/</span><button @click="navigate(crumb.path)">{{ crumb.name }}</button></template>
          <span v-if="query.trim()">/ 搜索结果（所有来源）</span>
        </nav>
        <div v-if="!selectedRoot && !query.trim()" class="skill-folder-grid">
          <article v-for="item in sources" :key="item.id" class="skill-folder-card">
            <button class="skill-folder-open" @click="navigate('', item.id)"><span class="skill-folder-icon" aria-hidden="true">▱</span><span><strong>{{ item.label }}</strong><small>{{ count(item) }} 个 Skill</small><span class="skill-path">{{ item.path }}</span></span><span aria-hidden="true">›</span></button>
            <p v-if="item.error" class="skill-error">{{ item.error }}</p><p v-else-if="!item.exists" class="skill-muted">目录尚不存在</p>
          </article>
        </div>
        <p v-if="source?.error" class="skill-error" role="alert">{{ source.error }}</p>
        <div v-if="currentEntry && !query.trim()" class="skill-current-folder">
          <div><h3>{{ currentEntry.name }}</h3><span>{{ currentEntry.skill_count }} 个 Skill · {{ currentEntry.folder_count }} 个子文件夹</span></div>
          <div class="skill-actions"><ActionButton compact @click="organize('move', currentEntry)">整理文件夹</ActionButton><ActionButton compact @click="organize('delete', currentEntry)">删除</ActionButton></div>
          <p v-if="currentEntry.error" class="skill-error">{{ currentEntry.error }}</p>
        </div>
        <template v-if="folders.length">
          <h3 class="skill-section-label">文件夹 <small>{{ folders.length }}</small></h3>
          <div class="skill-folder-grid">
            <article v-for="folder in folders" :key="`${folder.root_id}:${folder.path}`" class="skill-folder-card">
              <button class="skill-folder-open" @click="navigate(folder.path, folder.root_id)"><span class="skill-folder-icon" aria-hidden="true">▱</span><span><strong>{{ folder.name }}</strong><small>{{ folder.skill_count }} 个 Skill · {{ folder.folder_count }} 个子文件夹</small><span v-if="query.trim()" class="skill-path">{{ sourceLabel(folder.root_id) }} · {{ folder.path }}</span></span><span aria-hidden="true">›</span></button>
              <p v-if="folder.error" class="skill-error">{{ folder.error }}</p>
              <div class="skill-card-actions"><button @click="organize('move', folder)">整理</button><button @click="organize('delete', folder)">删除</button></div>
            </article>
          </div>
        </template>
        <template v-if="skills.length">
          <h3 class="skill-section-label">{{ query.trim() ? '匹配的 Skills' : 'Skills' }} <small>{{ skills.length }}</small></h3>
          <div class="skill-card-grid">
            <article v-for="skill in skills" :key="`${skill.root_id}:${skill.path}`" class="skill-card">
              <button class="skill-card-open" @click="detail = skill"><span class="skill-card-heading"><span class="skill-monogram" aria-hidden="true">{{ skill.name.slice(0, 2).toUpperCase() }}</span><strong>{{ skill.name }}</strong><small v-if="skill.version">v{{ skill.version }}</small></span><span class="skill-description">{{ skill.description || '尚无用途说明，点击查看文件详情。' }}</span><span class="skill-path">{{ skill.path }}</span></button>
              <p v-if="skill.error" class="skill-error">说明格式有误 · 查看详情</p>
              <p v-if="skill.shadowed_by" class="skill-muted">同路径优先使用：{{ skill.shadowed_by }}</p>
              <div class="skill-card-footer"><span class="skill-muted">{{ sourceLabel(skill.root_id) }}{{ skill.used_by.length ? ` · ${skill.used_by.length} 处引用` : '' }}</span><div class="skill-card-actions"><button @click="detail = skill">详情</button><button @click="organize('move', skill)">整理</button><button @click="organize('delete', skill)">删除</button></div></div>
            </article>
          </div>
        </template>
        <div v-if="!visible.length && !loading && !error && !source?.error" class="skill-empty"><strong>{{ query.trim() ? '没有匹配的 Skill 或文件夹' : '这个文件夹还没有 Skill' }}</strong><p>{{ query.trim() ? '换一个名称、用途关键词或路径试试。' : '新建分类文件夹，或通过「整理」把已有 Skill 移到这里。' }}</p><ActionButton v-if="query.trim()" compact @click="query = ''">清空搜索</ActionButton></div>
      </main>
    </div>
    <details v-if="trash.length" class="skill-trash"><summary>回收区 · {{ trash.length }} 项</summary><div v-for="item in trash" :key="`${item.rootId}:${item.id}`" class="skill-trash-row"><span class="skill-path">{{ item.label }} · {{ item.path }}</span><ActionButton compact :disabled="loading" @click="restore(item.rootId, item.id)">恢复</ActionButton></div></details>
    <p v-if="source" class="skill-root-path">{{ source.label }} · {{ source.path }}</p>
    <SkillDetailDialog v-if="detail" :entry="detail" @close="detail = null" />
    <SkillOrganizeDialog v-if="editing && editingSource" :action="editing.action" :entry="editing.entry" :entries="editingSource.entries" :current="selectedRoot === editing.rootId ? current : ''" :root-id="editing.rootId" :source-path="editingSource.path" @close="editing = null" @saved="saved" />
  </section>
</template>

<style src="./SkillsSettingsPanel.css"></style>
