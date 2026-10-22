<script setup lang="ts">
import { ref } from 'vue'
import { t } from '../../i18n'
import type { ToolDefinition } from '../../toolsetEditor'
import type { ToolPromptDefinition } from '../../toolPromptEditor'
import SelectionButton from '../SelectionButton.vue'
import ToolsetSettingsForm from './ToolsetSettingsForm.vue'
import ToolPromptSettingsForm from './ToolPromptSettingsForm.vue'

defineProps<{ data: Record<string, unknown>; catalog: ToolDefinition[]; promptCatalog: ToolPromptDefinition[] }>()
const emit = defineEmits<{ 'update:data': [data: Record<string, unknown>] }>()
const tab = ref<'sets' | 'prompts'>('sets')
</script>

<template>
  <div class="tool-settings">
    <nav class="tool-settings-tabs" :aria-label="t('toolprompts.sections')">
      <SelectionButton :active="tab === 'sets'" @click="tab = 'sets'">{{ t('toolprompts.sets') }}</SelectionButton>
      <SelectionButton :active="tab === 'prompts'" @click="tab = 'prompts'">{{ t('toolprompts.title') }}</SelectionButton>
    </nav>
    <ToolsetSettingsForm v-if="tab === 'sets'" :data="data" :catalog="catalog" @update:data="emit('update:data', $event)" />
    <ToolPromptSettingsForm v-else :data="data" :catalog="promptCatalog" @update:data="emit('update:data', $event)" />
  </div>
</template>

<style scoped>
.tool-settings { min-height: 0; overflow: auto; }
.tool-settings-tabs { display: flex; gap: 8px; padding: 16px 20px 0; }
</style>
