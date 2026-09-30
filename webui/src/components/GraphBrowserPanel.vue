<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { selectFolder, type GraphInfo, type GraphProfile } from '../api'
import ActionButton from './ActionButton.vue'
import DangerButton from './DangerButton.vue'
import FormSelect from './FormSelect.vue'
import FormTextInput from './FormTextInput.vue'
import GraphContents from './graph-browser/GraphContents.vue'
import { useGlobalState } from '../composables/useGlobalState'
import { t } from '../i18n'

const props = defineProps<{
  graphId: string; graphNameInput: string; graphWorkingPathInput: string
  graphLoading: boolean; graphMemoryClearingId: string
  graphs: GraphInfo[]; graphProfiles: GraphProfile[]; selectedGraphProfileId: string
}>()
const emit = defineEmits<{
  'update:graphNameInput': [value: string]
  'update:graphWorkingPathInput': [value: string]
  'update:selectedGraphProfileId': [value: string]
  graphPathError: [message: string]
  saveGraphConfig: []; saveGraphProfile: []; createGraphFromProfile: []; deleteGraphProfile: []; refreshGraphs: []
  loadGraphConfig: [graph: GraphInfo]; clearGraphMemory: [graph: GraphInfo]
  deleteGraphConfig: [graph: GraphInfo]; toggleGraphVisibility: [graph: GraphInfo]
  navigateGraphNode: [payload: { graph: GraphInfo; nodeId: string }]
  navigateGraphGroup: [payload: { graph: GraphInfo; groupId: string }]
}>()
const { nodeGraphDrag, nodeGraphDropTargetId, nodeGraphMoveInProgress } = useGlobalState()
const expandedGraphId = ref(props.graphId)
watch(() => props.graphId, id => { expandedGraphId.value = id })
function toggle(graph: GraphInfo) { expandedGraphId.value = expandedGraphId.value === graph.id ? '' : graph.id }
function canDeleteGraph(graph: GraphInfo) {
  if (typeof graph.deletable === 'boolean') return graph.deletable
  return !graph.readonly
}

function onGraphInfoClick(graph: GraphInfo) {
  toggle(graph)
}

function onGraphInfoKeydown(graph: GraphInfo, event: KeyboardEvent) {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  toggle(graph)
}

function updateGraphName(value: string) {
  emit('update:graphNameInput', value)
}

function canReceiveDraggedNode(graph: GraphInfo) {
  return !!nodeGraphDrag.value?.moved
    && !nodeGraphMoveInProgress.value
    && graph.id !== nodeGraphDrag.value.sourceGraphId
}

function onGraphDropPointerEnter(graph: GraphInfo) {
  if (canReceiveDraggedNode(graph)) nodeGraphDropTargetId.value = graph.id
}

function onGraphDropPointerLeave(graph: GraphInfo) {
  if (nodeGraphDropTargetId.value === graph.id) nodeGraphDropTargetId.value = ''
}

function updateGraphWorkingPath(value: string) {
  emit('update:graphWorkingPathInput', value)
}

async function chooseGraphWorkingPath() {
  try {
    const res = await selectFolder(String(props.graphWorkingPathInput || ''))
    const selectedPath = String(res?.path || '').trim()
    if (selectedPath) {
      emit('update:graphWorkingPathInput', selectedPath)
      await nextTick()
      emit('saveGraphConfig')
    }
  } catch (e: any) {
    emit('graphPathError', String(e?.message || e))
  }
}

function updateSelectedGraphProfile(value: string) {
  emit('update:selectedGraphProfileId', value)
}

</script>

<template>
    <div class="graph-panel">
      <div class="graph-section-heading"><strong>{{ t('memory.currentGraph') }}</strong><span>{{ graphNameInput || graphId }}</span></div>
      <div class="graph-actions">
        <FormTextInput
          class="graph-input"
          :placeholder="t('memory.graphName')"
          :model-value="graphNameInput"
          @update:model-value="updateGraphName"
        />
        <ActionButton variant="primary" compact @click="emit('saveGraphConfig')">{{ t('common.save') }}</ActionButton>
        <ActionButton compact @click="emit('saveGraphProfile')">{{ t('memory.saveProfile') }}</ActionButton>
        <ActionButton compact @click="emit('refreshGraphs')">{{ t('common.refresh') }}</ActionButton>
      </div>
      <div class="graph-path-row">
        <FormTextInput
          class="graph-input graph-path-input"
          :placeholder="t('memory.graphWorkingPath')"
          :model-value="graphWorkingPathInput"
          @update:model-value="updateGraphWorkingPath"
          @blur="emit('saveGraphConfig')"
        />
        <ActionButton compact @click="chooseGraphWorkingPath">{{ t('memory.changeFolder') }}</ActionButton>
      </div>
      <div class="graph-actions">
        <FormSelect
          class="graph-input profile-input"
          :model-value="selectedGraphProfileId"
          @change="updateSelectedGraphProfile"
        >
          <option value="">{{ t('memory.profile') }}</option>
          <option v-for="profile in graphProfiles" :key="profile.id" :value="profile.id">
            {{ profile.name || profile.id }}
          </option>
        </FormSelect>
        <ActionButton
          variant="primary"
          compact
          :disabled="!selectedGraphProfileId"
          @click="emit('createGraphFromProfile')"
        >
          CreateFromProfile
        </ActionButton>
        <DangerButton
          compact
          :disabled="!selectedGraphProfileId"
          @click="emit('deleteGraphProfile')"
        >
          DeleteProfile
        </DangerButton>
      </div>

      <div class="graph-section-heading"><strong>{{ t('memory.graphs') }}</strong><span>{{ graphs.length }}</span></div>
      <p class="graph-hierarchy-hint">{{ t('memory.graphHierarchyHint') }}</p>
      <div class="graph-list">
        <div v-if="graphLoading" class="graph-empty">{{ t('memory.loadingGraphs') }}</div>
        <div v-else-if="graphs.length === 0" class="graph-empty">{{ t('memory.noGraphs') }}</div>
        <div v-else class="graph-items">
          <div
            v-for="graph in graphs"
            :key="graph.id"
            class="graph-item-shell"
            :class="{
              'graph-current': graph.id === graphId,
              'node-drop-available': canReceiveDraggedNode(graph),
              'node-drop-target': nodeGraphDropTargetId === graph.id,
            }"
            @pointerenter="onGraphDropPointerEnter(graph)"
            @pointerleave="onGraphDropPointerLeave(graph)"
          >
            <div class="graph-item">
              <div
                class="graph-info graph-info-clickable"
                tabindex="0"
                role="button"
                :aria-expanded="expandedGraphId === graph.id"
                @click="onGraphInfoClick(graph)"
                @keydown="onGraphInfoKeydown(graph, $event)"
              >
                <div class="graph-name-row">
                  <span class="graph-expander">{{ expandedGraphId === graph.id ? '-' : '+' }}</span>
                  <span class="graph-kind">Graph</span><div class="graph-name">{{ graph.name }}</div><span v-if="graph.id === graphId" class="graph-current-label">{{ t('memory.current') }}</span>
                </div>
                <div class="graph-meta">{{ graph.updated_at || graph.id }}</div>
                <div v-if="nodeGraphDropTargetId === graph.id" class="graph-node-drop-hint">
                  {{ t('memory.dropNodeToMove') }}
                </div>
              </div>
              <div class="graph-item-actions">
                <ActionButton
                  v-if="graph.visibility_editable"
                  compact
                  @click="emit('toggleGraphVisibility', graph)"
                >
                  {{ graph.private ? 'Public' : 'Private' }}
                </ActionButton>
                <ActionButton compact @click="emit('loadGraphConfig', graph)">{{ t('memory.load') }}</ActionButton>
                <DangerButton
                  compact
                  :disabled="graphMemoryClearingId === graph.id"
                  @click="emit('clearGraphMemory', graph)"
                >
                  {{ graphMemoryClearingId === graph.id ? 'Clearing...' : 'ClearMemory' }}
                </DangerButton>
                <DangerButton v-if="canDeleteGraph(graph)" compact @click="emit('deleteGraphConfig', graph)">{{ t('common.delete') }}</DangerButton>
              </div>
            </div>
            <GraphContents v-if="expandedGraphId === graph.id" :key="graph.id" :graph="graph"
              :refresh-key="graphs" @navigate-node="emit('navigateGraphNode', { graph, nodeId: $event })"
              @open-group="emit('navigateGraphGroup', { graph, groupId: $event })" />
          </div>
        </div>
      </div>
    </div>

</template>

<style scoped src="./graph-browser/graphBrowser.css"></style>
