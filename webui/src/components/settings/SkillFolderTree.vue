<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SkillEntry } from '../../skillsApi'
const props = defineProps<{ entries: SkillEntry[]; parent?: string; current: string }>()
const emit = defineEmits<{ navigate: [path: string] }>()
const collapsed = ref(new Set<string>())
const folders = computed(() => props.entries.filter(entry => entry.kind === 'folder' && entry.parent === (props.parent || '')))
function toggle(path: string) {
  const next = new Set(collapsed.value)
  if (next.has(path)) next.delete(path); else next.add(path)
  collapsed.value = next
}
</script>

<template>
  <ul class="skill-tree-list">
    <li v-for="folder in folders" :key="folder.path">
      <div class="skill-tree-row" :class="{ selected: current === folder.path }">
        <button v-if="folder.folder_count" class="skill-tree-toggle" :aria-label="`${collapsed.has(folder.path) ? '展开' : '折叠'} ${folder.name}`" :aria-expanded="!collapsed.has(folder.path)" @click="toggle(folder.path)">{{ collapsed.has(folder.path) ? '›' : '⌄' }}</button>
        <span v-else class="skill-tree-spacer" />
        <button class="skill-tree-link" :title="folder.path" @click="emit('navigate', folder.path)"><span>{{ folder.name }}</span><small>{{ folder.skill_count }}</small></button>
      </div>
      <SkillFolderTree v-if="!collapsed.has(folder.path)" :entries="entries" :parent="folder.path" :current="current" @navigate="emit('navigate', $event)" />
    </li>
  </ul>
</template>
