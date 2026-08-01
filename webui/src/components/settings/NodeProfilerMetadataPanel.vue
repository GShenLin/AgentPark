<script setup lang="ts">
import ActionButton from '../ActionButton.vue'
import ExpandableTextarea from '../ExpandableTextarea.vue'
import FormTextInput from '../FormTextInput.vue'

defineProps<{
  nodeTypeId: string
  saving: boolean
}>()

defineEmits<{
  format: []
}>()

const nodeName = defineModel<string>('nodeName', { required: true })
const description = defineModel<string>('description', { required: true })
const sourceGraphId = defineModel<string>('sourceGraphId', { required: true })
const sourceNodeId = defineModel<string>('sourceNodeId', { required: true })
const eventRulesContent = defineModel<string>('eventRulesContent', { required: true })
</script>

<template>
  <details class="profile-metadata">
    <summary>
      <span>Profile metadata and event rules</span>
      <span aria-hidden="true">›</span>
    </summary>
    <div class="profile-metadata-content">
      <div class="profile-metadata-grid">
        <label>
          <span>Node type</span>
          <FormTextInput :model-value="nodeTypeId" readonly />
        </label>
        <label>
          <span>Node name</span>
          <FormTextInput v-model="nodeName" placeholder="Optional" />
        </label>
        <label class="profile-description-field">
          <span>Description</span>
          <ExpandableTextarea
            v-model="description"
            title="Profile description"
            aria-label="Profile description"
            :rows="3"
          />
        </label>
        <label>
          <span>Source graph</span>
          <FormTextInput v-model="sourceGraphId" placeholder="Optional" />
        </label>
        <label>
          <span>Source node</span>
          <FormTextInput v-model="sourceNodeId" placeholder="Optional" />
        </label>
      </div>
      <div class="profile-event-head">
        <div>
          <strong>Event rules</strong>
          <span>Advanced profile data; preserved independently from node fields.</span>
        </div>
        <ActionButton compact :disabled="saving" @click="$emit('format')">Format</ActionButton>
      </div>
      <ExpandableTextarea
        v-model="eventRulesContent"
        title="Profile event rules JSON"
        spellcheck="false"
        aria-label="Profile event rules JSON"
        :rows="8"
        min-height="160px"
      />
    </div>
  </details>
</template>

<style scoped>
.profile-metadata {
  border: 1px solid var(--theme-panel-node-side-editor-input-border, var(--border-subtle));
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.2);
  overflow: hidden;
}

summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 11px 12px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  list-style: none;
  user-select: none;
}

summary::-webkit-details-marker {
  display: none;
}

summary span:last-child {
  color: var(--text-tertiary);
  font-size: 18px;
  line-height: 1;
  transition: transform 0.16s ease;
}

details[open] > summary span:last-child {
  transform: rotate(90deg);
}

.profile-metadata-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 2px 12px 12px;
}

.profile-metadata-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.profile-description-field {
  grid-column: 1 / -1;
}

label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

label > span {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
}

.profile-event-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.profile-event-head > div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.profile-event-head strong {
  color: var(--text-primary);
  font-size: 12px;
}

.profile-event-head span {
  color: var(--text-tertiary);
  font-size: 11px;
}

@media (max-width: 760px) {
  .profile-metadata-grid {
    grid-template-columns: 1fr;
  }
}
</style>
