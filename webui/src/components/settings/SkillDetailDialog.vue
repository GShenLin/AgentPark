<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getSkillDetail, type SkillEntry, type SkillDetail } from '../../skillsApi'
import { useDialogLifecycle } from '../../composables/useDialogLifecycle'
import { renderSkillDocument } from './skillMarkdown'
import ActionButton from '../ActionButton.vue'

const props = defineProps<{ entry: SkillEntry }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLElement | null>(null)
const detail = ref<SkillDetail | null>(null)
const error = ref('')
const loading = ref(false)
const source = ref(false)
const html = computed(() => renderSkillDocument(detail.value?.content || ''))
useDialogLifecycle(dialog, ref(true), () => emit('close'))
watch(() => [props.entry.root_id, props.entry.path] as const, async ([rootId, path], _, onCleanup) => {
  let stale = false
  onCleanup(() => { stale = true })
  detail.value = null; error.value = ''; loading.value = true
  try { const result = await getSkillDetail(rootId, path); if (!stale) detail.value = result }
  catch (e) { if (!stale) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (!stale) loading.value = false }
}, { immediate: true })
</script>

<template>
  <div class="skill-overlay" @click.self="emit('close')">
    <section ref="dialog" class="skill-dialog skill-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="skill-detail-title" tabindex="-1">
      <header class="skill-dialog-head"><div><small>SKILL 详情 <span v-if="entry.version">· {{ entry.version }}</span></small><h2 id="skill-detail-title">{{ entry.name }}</h2></div><ActionButton compact @click="emit('close')">关闭</ActionButton></header>
      <div class="skill-detail-body">
        <p class="skill-description">{{ entry.description }}</p>
        <p class="skill-path">{{ entry.path }}/SKILL.md</p>
        <p v-if="entry.shadowed_by" class="skill-notice">同路径 Skill 优先使用「{{ entry.shadowed_by }}」中的版本；当前显示的是此来源中的说明。</p>
        <p v-if="entry.error || detail?.error || error" class="skill-error" role="alert">{{ error || detail?.error || entry.error }}</p>
        <details v-if="entry.used_by.length"><summary>{{ entry.used_by.length }} 处节点或模板引用</summary><ul><li v-for="location in entry.used_by" :key="location" class="skill-path">{{ location }}</li></ul></details>
        <p v-if="loading" role="status">正在读取完整说明…</p>
        <template v-if="detail">
          <div v-if="detail.tools.length || detail.mcp_servers.length" class="skill-dependencies"><strong>依赖能力</strong><span v-for="tool in detail.tools" :key="tool" class="skill-badge">{{ tool }}</span><span v-for="server in detail.mcp_servers" :key="server" class="skill-badge">MCP · {{ server }}</span></div>
          <div class="skill-document-head"><h3>使用说明</h3><ActionButton compact @click="source = !source">{{ source ? '阅读模式' : '查看原文' }}</ActionButton></div>
          <pre v-if="source" class="skill-source">{{ detail.content }}</pre>
          <div v-else class="skill-markdown" v-html="html" />
          <details v-if="detail.resources.length" class="skill-resources"><summary>附带资源 · {{ detail.resources.length }} 个文件</summary><ul><li v-for="resource in detail.resources" :key="resource.path"><strong>{{ resource.path }}</strong><small>{{ resource.type }} · {{ resource.size_bytes.toLocaleString() }} bytes</small><p v-if="resource.summary">{{ resource.summary }}</p></li></ul></details>
        </template>
      </div>
    </section>
  </div>
</template>
