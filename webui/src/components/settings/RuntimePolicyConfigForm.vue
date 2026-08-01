<script setup lang="ts">
import ExpandableTextarea from '../ExpandableTextarea.vue'
import FormCheckbox from '../FormCheckbox.vue'
import FormTextInput from '../FormTextInput.vue'
import RuntimePolicyStringListField from './RuntimePolicyStringListField.vue'

const props = defineProps<{
  data: Record<string, unknown>
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:data': [data: Record<string, unknown>]
}>()

function cloneData() {
  return JSON.parse(JSON.stringify(props.data)) as Record<string, unknown>
}

function section(name: string) {
  const value = props.data[name]
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function text(value: unknown) {
  return value == null ? '' : String(value)
}

function numberValue(sectionName: string, key: string) {
  const value = section(sectionName)[key]
  return typeof value === 'number' ? value : Number(value || 0)
}

function booleanValue(sectionName: string, key: string) {
  return section(sectionName)[key] === true
}

function stringList(sectionName: string, key: string) {
  const value = section(sectionName)[key]
  return Array.isArray(value) ? value.map((item) => String(item)) : []
}

function setRootField(key: string, value: unknown) {
  const next = cloneData()
  next[key] = value
  emit('update:data', next)
}

function setSectionField(sectionName: string, key: string, value: unknown) {
  const next = cloneData()
  next[sectionName] = {
    ...(next[sectionName] as Record<string, unknown> || {}),
    [key]: value,
  }
  emit('update:data', next)
}

function setSectionNumber(sectionName: string, key: string, value: string) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return
  setSectionField(sectionName, key, parsed)
}
</script>

<template>
  <div class="runtime-policy-form">
    <section class="policy-form-group">
      <header>
        <div>
          <h3>Metadata</h3>
          <p>Policy identity and human-readable description.</p>
        </div>
      </header>
      <div class="policy-form-grid">
        <label>
          <span>Policy ID</span>
          <FormTextInput :model-value="text(data.policy_id)" disabled />
        </label>
        <label>
          <span>Schema version</span>
          <FormTextInput :model-value="text(data.schema_version)" disabled />
        </label>
        <label>
          <span>Version</span>
          <FormTextInput :model-value="text(data.version)" :disabled="disabled" @update:model-value="setRootField('version', $event)" />
        </label>
        <label class="policy-form-wide">
          <span>Description</span>
          <ExpandableTextarea
            :model-value="text(data.description)"
            title="Policy description"
            aria-label="Policy description"
            :rows="2"
            min-height="64px"
            :disabled="disabled"
            @update:model-value="setRootField('description', $event)"
          />
        </label>
      </div>
    </section>

    <section class="policy-form-group">
      <header>
        <h3>Task direction</h3>
        <label class="policy-toggle">
          <FormCheckbox :model-value="booleanValue('task_direction', 'enabled')" :disabled="disabled" @update:model-value="setSectionField('task_direction', 'enabled', $event)" />
          <span>Enabled</span>
        </label>
      </header>
      <div class="policy-form-grid">
        <RuntimePolicyStringListField class="policy-form-wide" label="Required tools" :values="stringList('task_direction', 'required_tools')" :disabled="disabled" @update:values="setSectionField('task_direction', 'required_tools', $event)" />
        <RuntimePolicyStringListField class="policy-form-wide" label="Analysis tools" :values="stringList('task_direction', 'analysis_tools')" :disabled="disabled" @update:values="setSectionField('task_direction', 'analysis_tools', $event)" />
        <label>
          <span>Core prompt file</span>
          <FormTextInput :model-value="text(section('task_direction').core_prompt_file)" :disabled="disabled" @update:model-value="setSectionField('task_direction', 'core_prompt_file', $event)" />
        </label>
        <label>
          <span>Code prompt file</span>
          <FormTextInput :model-value="text(section('task_direction').code_prompt_file)" :disabled="disabled" @update:model-value="setSectionField('task_direction', 'code_prompt_file', $event)" />
        </label>
      </div>
    </section>

    <section class="policy-form-group">
      <header>
        <h3>Completion review</h3>
        <label class="policy-toggle">
          <FormCheckbox :model-value="booleanValue('completion_review', 'enabled')" :disabled="disabled" @update:model-value="setSectionField('completion_review', 'enabled', $event)" />
          <span>Enabled</span>
        </label>
      </header>
      <div class="policy-form-grid">
        <label>
          <span>Review passes</span>
          <FormTextInput type="number" min="1" max="5" :model-value="numberValue('completion_review', 'passes')" :disabled="disabled" @change="setSectionNumber('completion_review', 'passes', $event)" />
        </label>
        <label>
          <span>Prompt file</span>
          <FormTextInput :model-value="text(section('completion_review').prompt_file)" :disabled="disabled" @update:model-value="setSectionField('completion_review', 'prompt_file', $event)" />
        </label>
        <label class="policy-check"><FormCheckbox :model-value="booleanValue('completion_review', 'require_tool_executions')" :disabled="disabled" @update:model-value="setSectionField('completion_review', 'require_tool_executions', $event)" /><span>Require tool executions</span></label>
        <label class="policy-check"><FormCheckbox :model-value="booleanValue('completion_review', 'require_done_criteria')" :disabled="disabled" @update:model-value="setSectionField('completion_review', 'require_done_criteria', $event)" /><span>Require done criteria</span></label>
        <label class="policy-check"><FormCheckbox :model-value="booleanValue('completion_review', 'require_resolved_risks')" :disabled="disabled" @update:model-value="setSectionField('completion_review', 'require_resolved_risks', $event)" /><span>Require resolved risks</span></label>
      </div>
    </section>

    <section class="policy-form-group">
      <header>
        <h3>Implementation checkpoint</h3>
        <label class="policy-toggle">
          <FormCheckbox :model-value="booleanValue('implementation_checkpoint', 'enabled')" :disabled="disabled" @update:model-value="setSectionField('implementation_checkpoint', 'enabled', $event)" />
          <span>Enabled</span>
        </label>
      </header>
      <div class="policy-form-grid">
        <label><span>Evidence operation limit</span><FormTextInput type="number" min="1" max="1000" :model-value="numberValue('implementation_checkpoint', 'evidence_operation_limit')" :disabled="disabled" @change="setSectionNumber('implementation_checkpoint', 'evidence_operation_limit', $event)" /></label>
        <label><span>Workspace tool</span><FormTextInput :model-value="text(section('implementation_checkpoint').workspace_tool)" :disabled="disabled" @update:model-value="setSectionField('implementation_checkpoint', 'workspace_tool', $event)" /></label>
        <RuntimePolicyStringListField label="Direct evidence tools" :values="stringList('implementation_checkpoint', 'direct_evidence_tools')" :disabled="disabled" @update:values="setSectionField('implementation_checkpoint', 'direct_evidence_tools', $event)" />
        <RuntimePolicyStringListField label="Workspace evidence kinds" :values="stringList('implementation_checkpoint', 'workspace_evidence_kinds')" :disabled="disabled" @update:values="setSectionField('implementation_checkpoint', 'workspace_evidence_kinds', $event)" />
        <RuntimePolicyStringListField label="Patch tools" :values="stringList('implementation_checkpoint', 'patch_tools')" :disabled="disabled" @update:values="setSectionField('implementation_checkpoint', 'patch_tools', $event)" />
        <RuntimePolicyStringListField label="Workspace patch kinds" :values="stringList('implementation_checkpoint', 'workspace_patch_kinds')" :disabled="disabled" @update:values="setSectionField('implementation_checkpoint', 'workspace_patch_kinds', $event)" />
        <label class="policy-form-wide"><span>Prompt file</span><FormTextInput :model-value="text(section('implementation_checkpoint').prompt_file)" :disabled="disabled" @update:model-value="setSectionField('implementation_checkpoint', 'prompt_file', $event)" /></label>
      </div>
    </section>

    <section class="policy-form-group">
      <header>
        <h3>Context compaction</h3>
        <label class="policy-toggle">
          <FormCheckbox :model-value="booleanValue('context_compaction', 'enabled')" :disabled="disabled" @update:model-value="setSectionField('context_compaction', 'enabled', $event)" />
          <span>Enabled</span>
        </label>
      </header>
      <div class="policy-form-grid">
        <label><span>Every tool calls</span><FormTextInput type="number" min="0" max="10000" :model-value="numberValue('context_compaction', 'every_tool_calls')" :disabled="disabled" @change="setSectionNumber('context_compaction', 'every_tool_calls', $event)" /></label>
        <label><span>Input tokens</span><FormTextInput type="number" min="0" max="100000000" :model-value="numberValue('context_compaction', 'input_tokens')" :disabled="disabled" @change="setSectionNumber('context_compaction', 'input_tokens', $event)" /></label>
        <label><span>Current input tokens</span><FormTextInput type="number" min="0" max="10000000" :model-value="numberValue('context_compaction', 'current_input_tokens')" :disabled="disabled" @change="setSectionNumber('context_compaction', 'current_input_tokens', $event)" /><small>Use this or Context percent, not both.</small></label>
        <label><span>Output tokens</span><FormTextInput type="number" min="0" max="100000000" :model-value="numberValue('context_compaction', 'output_tokens')" :disabled="disabled" @change="setSectionNumber('context_compaction', 'output_tokens', $event)" /></label>
        <label><span>Context percent</span><FormTextInput type="number" min="0" max="100" :model-value="numberValue('context_compaction', 'context_percent')" :disabled="disabled" @change="setSectionNumber('context_compaction', 'context_percent', $event)" /><small>Use this or Current input tokens, not both.</small></label>
        <label><span>Max candidate characters</span><FormTextInput type="number" min="1000" max="2000000" :model-value="numberValue('context_compaction', 'max_candidate_chars')" :disabled="disabled" @change="setSectionNumber('context_compaction', 'max_candidate_chars', $event)" /></label>
        <label><span>Gate prompt file</span><FormTextInput :model-value="text(section('context_compaction').gate_prompt_file)" :disabled="disabled" @update:model-value="setSectionField('context_compaction', 'gate_prompt_file', $event)" /></label>
        <label><span>Retry prompt file</span><FormTextInput :model-value="text(section('context_compaction').retry_prompt_file)" :disabled="disabled" @update:model-value="setSectionField('context_compaction', 'retry_prompt_file', $event)" /></label>
      </div>
    </section>
  </div>
</template>

<style scoped src="./RuntimePolicyConfigForm.css"></style>
