<script setup lang="ts">
import type { AgentProfile } from '../../api'
import SelectionButton from '../SelectionButton.vue'

defineProps<{
  profiles: AgentProfile[]
  selectedProfileId: string
  loading: boolean
  disabled: boolean
}>()

defineEmits<{
  select: [profileId: string]
}>()
</script>

<template>
  <aside class="settings-split__side" aria-label="Node profilers">
    <div class="profile-list-head">
      <strong>Profiles</strong>
      <span>{{ profiles.length }}</span>
    </div>
    <SelectionButton
      v-for="profile in profiles"
      :key="profile.id"
      stacked
      class="settings-list-item"
      :active="profile.id === selectedProfileId"
      :disabled="loading || disabled"
      @click="$emit('select', profile.id)"
    >
      <span class="profile-option-name" :title="profile.name || profile.id">
        {{ profile.name || profile.id }}
      </span>
    </SelectionButton>
    <div v-if="!loading && profiles.length === 0" class="profile-empty">
      No Agent Profiles found in agent/*.json.
    </div>
  </aside>
</template>

<style scoped>

.profile-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px 12px;
  color: var(--text-secondary);
  font-size: 12px;
}

.profile-list-head span {
  color: var(--text-tertiary);
}

.profile-option-name {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  color: inherit;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-empty {
  padding: 24px 18px;
  color: var(--text-tertiary);
  font-size: 13px;
  line-height: 1.5;
}

</style>
