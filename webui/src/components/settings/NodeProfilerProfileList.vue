<script setup lang="ts">
import type { AgentProfile } from '../../api'

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
  <aside class="profile-list" aria-label="Node profilers">
    <div class="profile-list-head">
      <strong>Profiles</strong>
      <span>{{ profiles.length }}</span>
    </div>
    <button
      v-for="profile in profiles"
      :key="profile.id"
      type="button"
      class="profile-option"
      :class="{ active: profile.id === selectedProfileId }"
      :disabled="loading || disabled"
      @click="$emit('select', profile.id)"
    >
      <span class="profile-option-name" :title="profile.name || profile.id">
        {{ profile.name || profile.id }}
      </span>
    </button>
    <div v-if="!loading && profiles.length === 0" class="profile-empty">
      No Agent Profiles found in agent/*.json.
    </div>
  </aside>
</template>

<style scoped>
.profile-list {
  min-height: 0;
  overflow-y: auto;
  padding: 14px 10px;
  border-right: 1px solid var(--theme-panel-settings-panel-editor-border, var(--border-subtle));
  background: var(--theme-panel-settings-panel-tabs-background, var(--bg-secondary));
}

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

.profile-option {
  width: 100%;
  display: flex;
  align-items: center;
  margin-bottom: 4px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  text-align: left;
}

.profile-option-name {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  color: inherit;
  font-size: 11px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-option:hover,
.profile-option.active {
  background: var(--theme-panel-settings-panel-tabs-active-background, var(--accent-blue-soft));
  color: var(--theme-panel-settings-panel-tabs-active-text, var(--text-accent));
}

.profile-option.active {
  border-color: rgba(59, 130, 246, 0.25);
}

.profile-empty {
  padding: 24px 18px;
  color: var(--text-tertiary);
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 960px) {
  .profile-list {
    min-height: auto;
    max-height: 220px;
    border-right: 0;
    border-bottom: 1px solid var(--border-subtle);
  }
}
</style>
