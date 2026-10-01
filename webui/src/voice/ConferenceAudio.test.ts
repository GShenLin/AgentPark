import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ConferenceAudio } from './ConferenceAudio'

class GraphNode {
  edges = new Set<GraphNode>()
  gain = { value: 1 }
  connect(target: GraphNode) { this.edges.add(target); return target }
  disconnect(target?: GraphNode) {
    if (target && !this.edges.delete(target)) throw new Error('Missing audio connection')
    if (!target) this.edges.clear()
  }
}
function stream() {
  const track = { enabled: true, onended: null, stop: vi.fn() }
  return { track, getTracks: () => [track], getAudioTracks: () => [track] }
}
class Context {
  static last: Context
  destination = new GraphNode()
  sources = new Map<unknown, GraphNode>()
  outputs = new Map<unknown, GraphNode>()
  close = vi.fn(async () => {})
  constructor() { Context.last = this }
  async resume() {}
  createMediaStreamSource(input: unknown) { const node = new GraphNode(); this.sources.set(input, node); return node }
  createMediaStreamDestination() { const node = Object.assign(new GraphNode(), { stream: stream() }); this.outputs.set(node.stream, node); return node }
  createGain() { return new GraphNode() }
}
const microphone = stream()
const media = (value: ReturnType<typeof stream>) => value as unknown as MediaStream
beforeEach(() => {
  vi.clearAllMocks(); microphone.track.enabled = true
  vi.stubGlobal('AudioContext', Context)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async () => microphone) } })
})
afterEach(() => vi.unstubAllGlobals())

it('routes microphone to all nodes and each remote voice only to the other nodes', async () => {
  const room = new ConferenceAudio(); await room.open(vi.fn())
  const a = room.input('a'), b = room.input('b'), c = room.input('c')
  const alice = stream(), bob = stream()
  room.receive('a', media(alice)); room.receive('b', media(bob))
  const graph = Context.last
  const destinations = [a, b, c].map(s => graph.outputs.get(s)!)
  expect([...graph.sources.get(microphone)!.edges]).toEqual(destinations)
  const aEdges = graph.sources.get(alice)!.edges, bEdges = graph.sources.get(bob)!.edges
  expect(aEdges.has(destinations[0]!)).toBe(false)
  expect(aEdges.has(destinations[1]!)).toBe(true)
  expect(aEdges.has(destinations[2]!)).toBe(true)
  expect(bEdges.has(destinations[0]!)).toBe(true)
  expect(bEdges.has(destinations[1]!)).toBe(false)
  await room.close()
})

it('keeps peer-to-peer sound when the user mutes their microphone or stops listening', async () => {
  const room = new ConferenceAudio(); await room.open(vi.fn())
  room.input('a'); const b = room.input('b'); const alice = stream()
  room.receive('a', media(alice)); room.mutePlayback('a', true); room.muteMicrophone(true)
  expect(microphone.track.enabled).toBe(false)
  const edges = [...Context.last.sources.get(alice)!.edges]
  expect(edges.find(node => node.edges.has(Context.last.destination))!.gain.value).toBe(0)
  expect(edges).toContain(Context.last.outputs.get(b))
  room.muteMicrophone(false); expect(microphone.track.enabled).toBe(true)
  await room.close()
})

it('connects later arrivals and removes only the departing participant', async () => {
  const room = new ConferenceAudio(); await room.open(vi.fn())
  const a = room.input('a'), alice = stream(); room.receive('a', media(alice))
  const b = room.input('b'), bob = stream(); room.receive('b', media(bob))
  expect(Context.last.sources.get(alice)!.edges.has(Context.last.outputs.get(b)!)).toBe(true)
  room.leave('a')
  expect(Context.last.sources.get(alice)!.edges.size).toBe(0)
  expect(Context.last.sources.get(bob)!.edges.has(Context.last.outputs.get(a)!)).toBe(false)
  expect(microphone.track.stop).not.toHaveBeenCalled()
  expect(Context.last.sources.get(microphone)!.edges.has(Context.last.outputs.get(b)!)).toBe(true)
  await room.close(); await room.close(); room.leave('b')
  expect(microphone.track.stop).toHaveBeenCalledOnce()
  expect(Context.last.close).toHaveBeenCalledOnce()
})

it('releases a late microphone grant when the user hangs up during permission prompt', async () => {
  let grant!: (value: typeof microphone) => void
  vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(new Promise(resolve => { grant = value => resolve(media(value)) }))
  const room = new ConferenceAudio(), opening = room.open(vi.fn())
  await room.close(); grant(microphone)
  await expect(opening).rejects.toThrow('通话已结束')
  expect(microphone.track.stop).toHaveBeenCalledOnce()
})
