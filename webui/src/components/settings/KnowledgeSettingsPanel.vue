<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import FormSelect from '../FormSelect.vue'
import KnowledgeLibraryForm from './KnowledgeLibraryForm.vue'
import {
  knowledgeCitation, listKnowledge, listKnowledgeDocuments, operateKnowledge, searchKnowledge, testKnowledge,
  type KnowledgeAction, type KnowledgeDocument, type KnowledgeLibrary, type KnowledgeSearch,
} from '../../knowledgeApi'

const libraries = ref<KnowledgeLibrary[]>([])
const editing = ref<KnowledgeLibrary | null>(null)
const showForm = ref(false)
const selected = ref('')
const documents = ref<KnowledgeDocument[]>([])
const cursor = ref<number | null>(null)
const stateFilter = ref('')
const query = ref('')
const mode = ref('hybrid')
const results = ref<KnowledgeSearch | null>(null)
const busy = ref(false)
const error = ref('')
const message = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const labels: Record<string, string> = {
  idle: '尚未开始', queued: '排队中', running: '处理中', stopping: '正在暂停', paused: '已暂停',
  failed: '任务失败', completed: '已完成', completed_with_errors: '已完成，部分文件失败',
  scan: '扫描目录', prune: '清理已删除文件', parse: '提取与分块', embedding: '向量化', pipeline: '解析 / 向量化并行处理',
  ready: '可检索', pending: '待处理', parsing: '解析中', error: '文件失败',
}
const label = (value: string) => labels[value] || value
const active = (item: KnowledgeLibrary) => ['queued', 'running', 'stopping'].includes(item.progress.status)
function fail(e: unknown) { error.value = e instanceof Error ? e.message : String(e) }
async function refresh() {
  const result = await listKnowledge()
  if (disposed) return
  libraries.value = result.libraries
  if (result.worker_error) error.value = result.worker_error
}
async function poll() {
  try { await refresh() } catch (e) { fail(e) }
  finally { if (!disposed) timer = setTimeout(poll, 3000) }
}
async function run(work: () => Promise<unknown>) {
  busy.value = true; error.value = ''; message.value = ''
  try { await work() } catch (e) { fail(e) }
  finally { busy.value = false }
}
async function operate(item: KnowledgeLibrary, action: KnowledgeAction) {
  await run(async () => { await operateKnowledge(item.id, action); await refresh() })
}
function edit(item: KnowledgeLibrary | null) { editing.value = item; showForm.value = true }
async function saved() { showForm.value = false; await run(refresh) }
async function inspect(item: KnowledgeLibrary) {
  selected.value = item.id; stateFilter.value = ''; results.value = null
  await loadDocuments()
}
async function loadDocuments(after = 0) {
  const key = selected.value
  await run(async () => {
    const page = await listKnowledgeDocuments(key, after, stateFilter.value)
    if (key === selected.value) { documents.value = page.items; cursor.value = page.next_cursor }
  })
}
async function search() {
  results.value = null
  await run(async () => { results.value = await searchKnowledge(selected.value, query.value, mode.value) })
}
async function test(item: KnowledgeLibrary) {
  await run(async () => { const result = await testKnowledge(item.id); await refresh(); message.value = `连接成功，已按模型返回配置为 ${result.dimensions} 维` })
}
onMounted(poll)
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="knowledge-panel">
    <div class="knowledge-actions"><ActionButton variant="primary" :disabled="busy" @click="edit(null)">添加文件夹知识库</ActionButton><ActionButton :disabled="busy" @click="run(refresh)">刷新</ActionButton></div>
    <p>面向大型本地笔记库：后台递归扫描、磁盘索引、增量更新和断点恢复。首次处理会调用你配置的 Embedding 服务，时间与费用取决于资料总量和模型。</p>
    <p>数十万文件请预留索引磁盘空间；超限、损坏和无文本 PDF 会显示明确错误。首版不执行 OCR。修改资料后点击增量扫描；暂停在当前处理步骤结束后生效。</p>
    <p v-if="error" class="knowledge-error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <KnowledgeLibraryForm v-if="showForm" :library="editing" @saved="saved" @cancel="showForm = false" />
    <p v-if="!libraries.length && !showForm">尚未添加知识库。选择资料文件夹并配置向量模型后开始索引。</p>
    <article v-for="item in libraries" :key="item.id" class="knowledge-card">
      <div class="knowledge-actions"><strong>{{ item.name }}</strong><span>{{ label(item.progress.status) }}</span><span v-if="item.progress.phase !== 'idle'">{{ label(item.progress.phase) }}</span></div>
      <p class="knowledge-path">{{ item.folder }}</p>
      <p>{{ item.embedding_model }} · {{ item.dimensions }} 维 · {{ item.allow_agents ? 'Skill 可读取' : '仅管理页可读取' }}</p>
      <div class="knowledge-counts">
        <span>本次发现 {{ item.progress.discovered.toLocaleString() }} 文件</span>
        <span>可检索 {{ (item.progress.documents.ready || 0).toLocaleString() }}</span>
        <span>待解析 {{ ((item.progress.documents.pending || 0) + (item.progress.documents.parsing || 0)).toLocaleString() }}</span>
        <span>待向量化 {{ (item.progress.documents.embedding || 0).toLocaleString() }}</span>
        <span>失败 {{ (item.progress.documents.error || 0).toLocaleString() }}</span>
        <span>已向量化 {{ (item.progress.chunks['1'] || 0).toLocaleString() }} 片段</span>
        <span v-if="item.progress.excluded">跳过链接 / junction {{ item.progress.excluded }}</span>
      </div>
      <p v-if="item.progress.current_path" class="knowledge-path">当前：{{ item.progress.current_path }}</p>
      <p v-if="item.progress.error" class="knowledge-error" role="alert">{{ item.progress.error }}</p>
      <div class="knowledge-actions">
        <ActionButton compact :disabled="busy || active(item)" @click="edit(item)">配置</ActionButton>
        <ActionButton compact :disabled="busy" @click="test(item)">测试模型</ActionButton>
        <ActionButton compact :disabled="busy || active(item) || item.progress.phase !== 'idle'" @click="operate(item, 'scan')">开始 / 增量扫描</ActionButton>
        <ActionButton v-if="active(item)" compact :disabled="busy || item.progress.status === 'stopping'" @click="operate(item, 'pause')">暂停</ActionButton>
        <ActionButton v-else-if="item.progress.phase !== 'idle'" compact :disabled="busy" @click="operate(item, 'resume')">继续任务</ActionButton>
        <ActionButton compact :disabled="busy || active(item) || !item.progress.documents.error" @click="operate(item, 'retry')">重试失败文件</ActionButton>
        <ActionButton compact :disabled="busy" @click="inspect(item)">文档与检索测试</ActionButton>
      </div>
      <small>知识库 ID：{{ item.id }}</small>
    </article>
    <section v-if="selected" class="knowledge-card">
      <h3>{{ libraries.find(item => item.id === selected)?.name }} · 文档与检索</h3>
      <form class="knowledge-actions" @submit.prevent="search">
        <FormTextInput v-model="query" required placeholder="输入自然语言问题或关键词" aria-label="知识库查询" />
        <FormSelect v-model="mode" aria-label="检索方式"><option value="hybrid">混合检索</option><option value="semantic">语义检索</option><option value="keyword">关键词检索</option></FormSelect>
        <ActionButton type="submit" :disabled="busy">检索</ActionButton>
      </form>
      <template v-if="results">
        <p v-if="results.partial">当前索引尚未完整完成，以下结果仅来自已成功发布的资料。</p>
        <p v-if="!results.matches.length">没有找到匹配片段。</p>
        <article v-for="hit in results.matches" :key="hit.chunk_id" class="knowledge-hit">
          <strong>{{ hit.path }}</strong><span> · {{ knowledgeCitation(hit) }} · {{ hit.channels.join(' + ') }}</span>
          <p v-if="hit.warning">{{ hit.warning }}</p><p v-if="hit.document_state !== 'ready'">此文件正在更新或更新失败，显示上一次成功索引。</p>
          <pre>{{ hit.text }}</pre>
        </article>
      </template>
      <div class="knowledge-actions">
        <FormSelect v-model="stateFilter" aria-label="文档状态"><option value="">全部状态</option><option value="error">失败文件</option><option value="ready">已完成</option><option value="pending">待处理</option><option value="embedding">待向量化</option></FormSelect>
        <ActionButton :disabled="busy" @click="loadDocuments()">刷新 / 第一页</ActionButton>
        <ActionButton :disabled="busy || cursor === null" @click="loadDocuments(cursor!)">下一页</ActionButton>
      </div>
      <ul class="knowledge-documents"><li v-for="doc in documents" :key="doc.id"><strong>{{ doc.path }}</strong> · {{ label(doc.state) }} · {{ doc.chunk_count }} 片段<p v-if="doc.error" class="knowledge-error">{{ doc.error }}</p><p v-if="doc.warning">{{ doc.warning }}</p></li></ul>
    </section>
    <p>Agent 节点选择 <code>knowledge</code> Skill 后，可列出、检索、读取原文并计算 Excel 表格；结果包含 PDF 页码、文本行号、Word 段落或 Excel 工作表与行列位置。</p>
  </section>
</template>

<style src="./KnowledgeSettingsPanel.css"></style>
