<script setup lang="ts">
import { ref } from 'vue'
import { configureSkillRoots, type SkillSource } from '../../skillsApi'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'

defineProps<{ sources: SkillSource[] }>()
const emit = defineEmits<{ changed: [] }>()
const path = ref('')
const busy = ref(false)
const error = ref('')
const removing = ref('')
async function change(operation: { action: 'add'; path: string } | { action: 'remove'; root_id: string }) {
  busy.value = true; error.value = ''
  try { await configureSkillRoots(operation); path.value = ''; removing.value = ''; emit('changed') }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
</script>

<template>
  <details class="skill-source-settings">
    <summary>管理加载路径 · {{ sources.length }} 个来源</summary>
    <p class="skill-muted">以下路径均属于运行 AgentPark 的设备。默认加载项目和用户目录，自定义目录按添加顺序加载。同一路径的 Skill 优先级：项目 → 用户 → 自定义。</p>
    <div v-for="source in sources" :key="source.id" class="skill-source-setting-row">
      <div><strong>{{ source.label }}</strong><p class="skill-path">{{ source.path }}</p><p v-if="source.error" class="skill-error">{{ source.error }}</p><span v-else-if="!source.exists" class="skill-muted">目录尚不存在</span><span v-else class="skill-muted">{{ source.entries.filter(entry => entry.kind === 'skill').length }} 个 Skill</span></div>
      <ActionButton v-if="source.kind === 'custom' && removing !== source.id" compact :disabled="busy" @click="removing = source.id">移除加载路径</ActionButton>
      <div v-if="removing === source.id"><p>停止加载这个路径，保留其中的全部文件。</p><div class="skill-actions"><ActionButton compact :disabled="busy" @click="removing = ''">取消</ActionButton><ActionButton compact :disabled="busy" @click="change({ action: 'remove', root_id: source.id })">确认移除</ActionButton></div></div>
    </div>
    <form class="skill-source-add" @submit.prevent="change({ action: 'add', path })"><label>添加 Skill 根文件夹<FormTextInput v-model="path" required :disabled="busy" placeholder="例如 D:\Shared\Skills（内含多个 Skill 文件夹）" /></label><ActionButton type="submit" :disabled="busy || !path.trim()">{{ busy ? '保存中…' : '添加加载路径' }}</ActionButton></form>
    <p v-if="error" class="skill-error" role="alert">{{ error }}</p>
  </details>
</template>
