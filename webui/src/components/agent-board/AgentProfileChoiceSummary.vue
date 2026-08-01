<script setup lang="ts">
import { computed } from 'vue'
import type { AgentProfile } from '../../api'
import { agentProfileDescription } from '../../composables/agentProfilePresentation'

const props = withDefaults(defineProps<{
  profile: AgentProfile
  showId?: boolean
  compact?: boolean
  showDescription?: boolean
}>(), {
  showId: true,
  compact: false,
  showDescription: true,
})

const description = computed(() => agentProfileDescription(props.profile))
</script>

<template>
  <span class="profile-choice-summary" :class="{ compact }">
    <span class="profile-choice-heading">
      <span class="profile-choice-name">{{ profile.name || profile.id }}</span>
      <span v-if="profile.profile_metadata" class="profile-choice-badges">
        <span class="profile-choice-family">{{ profile.profile_metadata.task_family }}</span>
        <span
          class="profile-choice-evidence"
          :title="profile.profile_metadata.provider_rationale"
        >
          {{ profile.profile_metadata.evidence_level }}
        </span>
        <span
          class="profile-choice-variant"
          :title="`A/B ${profile.profile_metadata.ab_test.experiment_id}: ${profile.profile_metadata.ab_test.variant}, peer ${profile.profile_metadata.ab_test.peer_profile_id}`"
        >
          {{ profile.profile_metadata.ab_test.variant }}
        </span>
      </span>
    </span>
    <span v-if="description && showDescription && !compact" class="profile-choice-description">
      {{ description }}
    </span>
    <span v-if="showId && profile.name && profile.name !== profile.id" class="profile-choice-id">
      {{ profile.id }}
    </span>
  </span>
</template>

<style scoped>
.profile-choice-summary {
  min-width: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  text-align: left;
}

.profile-choice-heading {
  min-width: 0;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.profile-choice-name,
.profile-choice-description,
.profile-choice-id {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.profile-choice-name,
.profile-choice-id {
  white-space: nowrap;
}

.profile-choice-name {
  min-width: 0;
  flex: 1;
  color: inherit;
  font-size: 12px;
  font-weight: 650;
}

.profile-choice-description {
  display: -webkit-box;
  color: rgba(148, 163, 184, 0.9);
  font-size: 10px;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.profile-choice-id {
  color: rgba(148, 163, 184, 0.78);
  font: 10px/1.3 'Consolas', 'Menlo', monospace;
}

.profile-choice-badges {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.profile-choice-family,
.profile-choice-evidence,
.profile-choice-variant {
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 999px;
  background: rgba(14, 116, 144, 0.16);
  color: rgba(125, 211, 252, 0.96);
  padding: 1px 5px;
  font-size: 9px;
  line-height: 1.35;
}

.profile-choice-variant {
  min-width: 18px;
  border-color: rgba(167, 139, 250, 0.32);
  background: rgba(109, 40, 217, 0.16);
  color: rgba(196, 181, 253, 0.98);
  text-align: center;
}

.profile-choice-evidence {
  border-color: rgba(74, 222, 128, 0.28);
  background: rgba(22, 101, 52, 0.16);
  color: rgba(134, 239, 172, 0.96);
}

.profile-choice-summary.compact {
  gap: 1px;
}

.profile-choice-summary.compact .profile-choice-name {
  font-size: 11px;
}
</style>
