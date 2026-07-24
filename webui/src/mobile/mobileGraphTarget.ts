import {
  listMobileGraphs,
  listMobilePcs,
  type MobileGraph,
  type MobileGraphInstance,
  type MobilePc,
} from '../api'

export type MobileGraphTarget = {
  pcs: MobilePc[]
  pc: MobilePc
  graphInstances: MobileGraphInstance[]
  graph: MobileGraph
}

type ResolveMobileGraphTargetOptions = {
  knownPcs?: MobilePc[]
  selectedPcId?: string
  selectedGraphInstances?: MobileGraphInstance[]
}

function findGraph(instances: MobileGraphInstance[], graphId: string) {
  return instances.flatMap((instance) => instance.graphs).find((graph) => graph.id === graphId) || null
}

export async function resolveMobileGraphTarget(
  graphId: string,
  options: ResolveMobileGraphTargetOptions = {},
): Promise<MobileGraphTarget> {
  const targetGraphId = String(graphId || '').trim()
  if (!targetGraphId) throw new Error('Graph id is required')

  const pcs = options.knownPcs?.length ? options.knownPcs : await listMobilePcs()
  const selectedPcId = String(options.selectedPcId || '').trim()
  const orderedPcs = [...pcs].sort((left, right) => {
    const priority = (pc: MobilePc) => pc.id === 'local' ? 0 : pc.id === selectedPcId ? 1 : 2
    return priority(left) - priority(right)
  })

  for (const pc of orderedPcs) {
    const cachedInstances = pc.id === selectedPcId ? options.selectedGraphInstances || [] : []
    const cachedGraph = findGraph(cachedInstances, targetGraphId)
    if (cachedGraph) return { pcs, pc, graphInstances: cachedInstances, graph: cachedGraph }

    const graphInstances = await listMobileGraphs(pc.id)
    const graph = findGraph(graphInstances, targetGraphId)
    if (graph) return { pcs, pc, graphInstances, graph }
  }

  throw new Error(`Graph not found: ${targetGraphId}`)
}
