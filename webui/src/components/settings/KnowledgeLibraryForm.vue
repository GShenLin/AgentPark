<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import FormCheckbox from '../FormCheckbox.vue'
import ApiKeyAliasField from './ApiKeyAliasField.vue'
import { selectFolder } from '../../api'
import { emptyKnowledgeConfig, saveKnowledge, type KnowledgeLibrary } from '../../knowledgeApi'

const props = defineProps<{ library: KnowledgeLibrary | null }>()
const emit = defineEmits<{ saved: []; cancel: [] }>()
const form = ref(emptyKnowledgeConfig())
const busy = ref(false)
const error = ref('')
const endpoint = computed(() => {
  const url = form.value.embedding_url.trim().replace(/\/+$/, '')
  return url ? (url.endsWith('/embeddings') ? url : `${url}/embeddings`) : ''
})
watch(() => props.library, library => {
  const defaults = emptyKnowledgeConfig()
  if (library) {
    for (const field of Object.keys(defaults) as (keyof typeof defaults)[]) {
      Object.assign(defaults, { [field]: library[field] })
    }
  }
  form.value = defaults
  error.value = ''
}, { immediate: true })
async function chooseFolder() {
  try {
    const result = await selectFolder(form.value.folder)
    if (result.path) form.value.folder = result.path
  } catch (e) { error.value = String(e instanceof Error ? e.message : e) }
}
async function save() {
  busy.value = true; error.value = ''
  try {
    await saveKnowledge(form.value, props.library?.id)
    emit('saved')
  } catch (e) { error.value = String(e instanceof Error ? e.message : e) }
  finally { busy.value = false }
}
</script>

<template>
  <form class="knowledge-form" @submit.prevent="save">
    <p>直接读取后端机器上的资料文件夹，递归索引 PDF、Markdown、TXT、Word（DOCX / DOC）和 Excel（XLSX / XLS）；原文件保持不变。</p>
    <p>DOC 需要后端安装 LibreOffice。Excel 保留工作表和行列位置，公式读取已保存的计算结果；图片、图表和宏不参与解析。</p>
    <label>知识库名称<FormTextInput v-model="form.name" required /></label>
    <label>资料文件夹
      <div class="knowledge-actions"><FormTextInput v-model="form.folder" :disabled="!!library" required placeholder="D:\Notes" />
        <ActionButton :disabled="!!library" @click="chooseFolder">选择文件夹</ActionButton></div>
    </label>
    <label>Embedding Base URL / 完整接口地址<FormTextInput v-model="form.embedding_url" :disabled="!!library" required type="url" /></label>
    <small>支持 OpenAI 兼容文本向量接口；填写 Base URL 时自动补全 /embeddings。</small>
    <small v-if="endpoint">实际请求地址：{{ endpoint }}</small>
    <div class="knowledge-grid">
      <label>Embedding 模型名称<FormTextInput v-model="form.embedding_model" :disabled="!!library" required /></label>
      <div>向量维度：由模型响应自动检测，无需填写。<small v-if="library">当前配置 {{ library.dimensions }} 维；尚未写入向量时可自动校正。</small></div>
    </div>
    <ApiKeyAliasField v-model="form.api_key_alias" />
    <small>与 Model Provider 共用已有 Key；点击 Add 可添加并自动选中。本地无认证服务可选 Unset。</small>
    <label class="knowledge-check"><FormCheckbox v-model="form.allow_agents" />允许选用了 knowledge Skill 的节点读取此知识库</label>
    <details><summary>处理与资源配置</summary>
      <div class="knowledge-grid">
        <label>每次 Embedding 的片段数<FormTextInput :model-value="form.batch_size" type="number" min="1" max="128" @update:model-value="form.batch_size = Number($event)" /></label>
        <label>请求超时（秒）<FormTextInput :model-value="form.request_timeout" type="number" min="5" max="300" @update:model-value="form.request_timeout = Number($event)" /></label>
        <label>429 重试等待时间（秒）<FormTextInput :model-value="form.retry_interval_seconds" type="number" min="1" max="300" step="1" @update:model-value="form.retry_interval_seconds = Number($event)" /><small>仅在收到 429 时等待，默认 5 秒；每批最多重试 3 次。</small></label>
        <label>分块字符数<FormTextInput :model-value="form.chunk_size" :disabled="!!library" type="number" min="256" max="8000" @update:model-value="form.chunk_size = Number($event)" /></label>
        <label>重叠字符数<FormTextInput :model-value="form.chunk_overlap" :disabled="!!library" type="number" min="0" max="1000" @update:model-value="form.chunk_overlap = Number($event)" /></label>
        <label>单文件上限（MB）<FormTextInput :model-value="form.max_file_mb" type="number" min="1" max="4096" @update:model-value="form.max_file_mb = Number($event)" /></label>
        <label>单页字符上限<FormTextInput :model-value="form.max_page_chars" type="number" min="10000" max="2000000" @update:model-value="form.max_page_chars = Number($event)" /></label>
        <label>Excel 表头行<FormTextInput :model-value="form.spreadsheet_header_row" :disabled="!!library" type="number" min="0" max="1048576" step="1" @update:model-value="form.spreadsheet_header_row = Number($event)" /><small>0 表示不指定；若每张表的第 1 行都是表头，填 1 可在数据片段中附带列名。创建后固定。</small></label>
      </div>
    </details>
    <p>测试模型或启动索引时自动检测维度，已有向量后维度固定。模型地址、名称、目录和分块配置创建后固定。保存后点击“开始 / 增量扫描”才会处理资料并调用模型。</p>
    <p v-if="error" class="knowledge-error" role="alert">{{ error }}</p>
    <div class="knowledge-actions"><ActionButton type="submit" variant="primary" :disabled="busy">{{ busy ? '保存中…' : '保存知识库' }}</ActionButton><ActionButton :disabled="busy" @click="emit('cancel')">取消</ActionButton></div>
  </form>
</template>
