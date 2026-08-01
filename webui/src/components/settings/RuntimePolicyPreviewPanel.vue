<script setup lang="ts">
import type { RuntimePolicyPreview } from '../../api'
import ActionButton from '../ActionButton.vue'
import ExpandableTextarea from '../ExpandableTextarea.vue'

defineProps<{
  preview: RuntimePolicyPreview | null
  saving: boolean
  resolving: boolean
}>()

defineEmits<{
  resolve: []
}>()
</script>

<template>
  <details class="runtime-policy-preview">
    <summary>
      <span>Effective RuntimePolicy</span>
      <span aria-hidden="true">›</span>
    </summary>
    <div class="runtime-policy-content">
      <div class="runtime-policy-head">
        <div>
          <strong>Resolved policy and prompt manifest</strong>
          <span>Empty Profile value resolves to the catalog default.</span>
        </div>
        <ActionButton
          compact
          :disabled="saving || resolving"
          @click="$emit('resolve')"
        >
          {{ resolving ? 'Resolving...' : 'Resolve preview' }}
        </ActionButton>
      </div>
      <template v-if="preview">
        <div class="runtime-policy-summary">
          <span>{{ preview.manifest.policy_id }}@{{ preview.manifest.policy_version }}</span>
          <span>{{ preview.manifest.selection_source }}</span>
          <code>{{ preview.manifest.effective_sha256 }}</code>
        </div>
        <div class="runtime-policy-prompts">
          <div
            v-for="prompt in preview.manifest.prompts"
            :key="prompt.layer"
            class="runtime-policy-prompt"
          >
            <strong>{{ prompt.layer }}</strong>
            <span>{{ prompt.chars }} chars · {{ prompt.source }}</span>
            <code>{{ prompt.sha256 }}</code>
          </div>
        </div>
        <ExpandableTextarea
          :model-value="`${JSON.stringify(preview.policy, null, 2)}\n`"
          title="Effective RuntimePolicy JSON"
          aria-label="Effective RuntimePolicy JSON"
          min-height="160px"
          readonly
        />
      </template>
    </div>
  </details>
</template>

<style scoped>
.runtime-policy-preview {
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

.runtime-policy-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 2px 12px 12px;
}

.runtime-policy-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.runtime-policy-head > div,
.runtime-policy-summary,
.runtime-policy-prompt {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.runtime-policy-head strong {
  color: var(--text-primary);
  font-size: 12px;
}

.runtime-policy-head span,
.runtime-policy-prompt span,
.runtime-policy-summary span {
  color: var(--text-tertiary);
  font-size: 11px;
}

.runtime-policy-summary,
.runtime-policy-prompts {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  padding: 10px;
}

.runtime-policy-prompts {
  display: grid;
  gap: 10px;
}

.runtime-policy-summary code,
.runtime-policy-prompt code {
  color: rgba(148, 163, 184, 0.86);
  font-size: 10px;
  overflow-wrap: anywhere;
}

</style>
