import { ref, type Ref } from 'vue'
import { listGraphs, saveGraph, setStartupGraphConfig, type GraphConfig, type GraphInfo } from '../../api'
import { useGlobalState } from '../../composables/useGlobalState'
import { t } from '../../i18n'

export function useNewGraph(options: {
  graphNameInput: Ref<string>
  graphWorkingPathInput: Ref<string>
  graphs: Ref<GraphInfo[]>
  graphStatus: Ref<string | null>
}) {
  const creating = ref(false)
  const state = useGlobalState()

  async function createNewGraph() {
    if (creating.value) return
    creating.value = true
    options.graphStatus.value = null
    try {
      // Allocate an independent identity. Never derive a new graph from the
      // current snapshot: that would copy nodes, routes and graph artifacts.
      const id = `graph-${crypto.randomUUID()}`
      const graph: GraphConfig = { id, name: id, working_path: '', nodes: [], output_routes: {} }
      const saved = await saveGraph(id, graph, { saveReason: 'new_empty_graph' })
      const created = { ...graph, id: saved.id, name: saved.name }
      state.selectedNodeId.value = null
      state.graphNodeFocusRequest.value = null
      state.currentGraphId.value = created.id
      state.currentGraphName.value = created.name
      state.currentGraphWorkingPath.value = ''
      options.graphNameInput.value = created.name
      options.graphWorkingPathInput.value = ''
      state.graphLoadRequest.value = created
      state.memoryMode.value = 'graph'
      state.memoryMeta.value = null
      options.graphs.value = [...options.graphs.value, saved]
      await setStartupGraphConfig(created.id, created.name)
      options.graphs.value = await listGraphs()
      options.graphStatus.value = t('memory.graphCreated')
    } catch (error: unknown) {
      options.graphStatus.value = error instanceof Error ? error.message : String(error)
    } finally {
      creating.value = false
    }
  }

  return { creating, createNewGraph }
}
