<script setup lang="ts">
import { computed, ref } from 'vue'
import { moveTargets, operateSkill, type SkillEntry, type SkillOperation } from '../../skillsApi'
import { useDialogLifecycle } from '../../composables/useDialogLifecycle'
import ActionButton from '../ActionButton.vue'
import FormTextInput from '../FormTextInput.vue'
import FormSelect from '../FormSelect.vue'

const props = defineProps<{ action: 'create_folder' | 'move' | 'delete'; entry?: SkillEntry; entries: SkillEntry[]; current: string; rootId: string; sourcePath: string }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const dialog = ref<HTMLElement | null>(null)
const parent = ref(props.entry ? props.entry.parent : props.current)
const name = ref(props.entry?.path.split('/').slice(-1)[0] || '')
const busy = ref(false)
const error = ref('')
const targets = computed(() => moveTargets(props.entries, props.entry?.path || ''))
const title = computed(() => ({ create_folder: '新建分类文件夹', move: '整理 · 移动或重命名', delete: '移入回收区' })[props.action])
const blocked = computed(() => props.action !== 'create_folder' && !!props.entry?.used_by.length)
function close() { if (!busy.value) emit('close') }
useDialogLifecycle(dialog, ref(true), close)
async function save() {
  busy.value = true; error.value = ''
  try {
    let operation: SkillOperation
    if (props.action === 'create_folder') operation = { root_id: props.rootId, action: props.action, parent: parent.value, name: name.value }
    else if (props.action === 'delete') operation = { root_id: props.rootId, action: props.action, path: props.entry!.path }
    else operation = { root_id: props.rootId, action: props.action, path: props.entry!.path, parent: parent.value, name: name.value }
    await operateSkill(operation)
    emit('saved')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
</script>

<template>
  <div class="skill-overlay" @click.self="close">
    <form ref="dialog" class="skill-dialog skill-organize-dialog" role="dialog" aria-modal="true" aria-labelledby="skill-organize-title" tabindex="-1" @submit.prevent="save">
      <header class="skill-dialog-head"><h2 id="skill-organize-title">{{ title }}</h2><ActionButton compact :disabled="busy" @click="close">取消</ActionButton></header>
      <div class="skill-detail-body">
        <p class="skill-path">加载来源：{{ sourcePath }}</p>
        <p v-if="entry" class="skill-path">{{ entry.path }}</p>
        <template v-if="action === 'delete'"><p>整个文件夹及其中的说明、脚本、素材都会移出已安装列表。</p><p v-if="entry?.kind === 'folder'">包含 {{ entry.skill_count }} 个 Skill、{{ entry.folder_count }} 个子文件夹。</p><p>删除后可在本页的「回收区」恢复。</p></template>
        <template v-else>
          <label class="skill-form-field">{{ action === 'move' ? '目标文件夹' : '上级文件夹' }}<FormSelect v-model="parent" :disabled="busy || blocked"><option value="">全部 Skills（根目录）</option><option v-for="target in targets" :key="target.path" :value="target.path">{{ target.path.split('/').join(' / ') }}</option></FormSelect></label>
          <label class="skill-form-field">文件夹名称<FormTextInput v-model="name" required pattern="[A-Za-z0-9][A-Za-z0-9_.\-]*" :disabled="busy || blocked" placeholder="例如 Game、Design、game-design" /></label>
          <p class="skill-muted">名称使用英文字母、数字、下划线、短横线或点，以字母或数字开头。Skill 内容与用途说明可以使用中文。</p>
          <p v-if="action === 'move'">移动会保留整个文件夹的内容，重命名不会改写 Skill 的说明和内部名称。</p>
        </template>
        <div v-if="blocked" class="skill-notice"><strong>请先解除以下引用</strong><p>这些节点或模板按原路径使用此 Skill。取消引用后即可整理，再在新位置重新选择。</p><ul><li v-for="location in entry?.used_by" :key="location" class="skill-path">{{ location }}</li></ul></div>
        <p v-if="error" class="skill-error" role="alert">{{ error }}</p>
        <footer class="skill-dialog-actions"><ActionButton type="submit" variant="primary" :disabled="busy || blocked">{{ busy ? '处理中…' : action === 'delete' ? '确认移入回收区' : '保存' }}</ActionButton></footer>
      </div>
    </form>
  </div>
</template>
