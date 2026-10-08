import { describe, expect, it, vi } from 'vitest'
import { BoardOffer } from './BoardOffer'

class Peer extends EventTarget {
  iceGatheringState = 'gathering'
  createOffer = vi.fn(async () => ({ type: 'offer', sdp: 'v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n' }))
  setLocalDescription = vi.fn(async () => {})
  emit(candidate: string | null) {
    this.dispatchEvent(Object.assign(new Event('icecandidate'), { candidate: candidate === null ? null : {
      candidate, sdpMid: '0', sdpMLineIndex: 0, type: 'host',
    } }))
  }
}
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }

describe('Board trickle offer', () => {
  it('sends the offer while discovery is still gathering, including after the old 20s deadline', async () => {
    vi.useFakeTimers()
    try {
      const pc = new Peer(), send = vi.fn(async (_packet: object) => {}), fail = vi.fn()
      const flow = new BoardOffer(pc as unknown as RTCPeerConnection, send, fail)
      await flow.start()
      expect(send.mock.calls[0]![0]).toMatchObject({ kind: 'offer' })
      await vi.advanceTimersByTimeAsync(25000)
      pc.emit('candidate:1 1 UDP 1 192.0.2.1 5000 typ host')
      await flush()
      expect(send.mock.calls[1]![0]).toMatchObject({ kind: 'ice_candidate', sequence: 0 })
      expect(fail).not.toHaveBeenCalled()
      flow.close()
    } finally { vi.useRealTimers() }
  })

  it('buffers early candidates until the signed offer and preserves ordering and completion', async () => {
    const pc = new Peer(), packets: object[] = []
    let release!: () => void
    const signing = new Promise<void>(resolve => { release = resolve })
    const flow = new BoardOffer(pc as unknown as RTCPeerConnection, async packet => {
      if (packet.kind === 'offer') await signing
      packets.push(packet)
    }, error => { throw error })
    const start = flow.start()
    await flush()
    pc.emit('candidate:1 1 UDP 1 192.0.2.1 5000 typ host'); pc.emit(''); pc.emit(null)
    expect(packets).toEqual([])
    release(); await start; await flush()
    expect(packets.map(p => (p as { kind: string }).kind)).toEqual(['offer', 'ice_candidate', 'ice_candidate'])
    expect(packets[2]).toMatchObject({ sequence: 1, candidate: null, sdp_mid: null, sdp_mline_index: null })
    flow.close()
  })

  it('cancelling during signing does not flush candidates or retain listeners', async () => {
    const pc = new Peer(), send = vi.fn(async (_packet: object) => {}), remove = vi.spyOn(pc, 'removeEventListener')
    const flow = new BoardOffer(pc as unknown as RTCPeerConnection, send, vi.fn())
    pc.emit('candidate:1 1 UDP 1 192.0.2.1 5000 typ host')
    flow.close(); await flow.start(); pc.emit(null); await flush()
    expect(send).not.toHaveBeenCalled()
    expect(remove).toHaveBeenCalledTimes(2)
  })

  it('reports send failures and stops sending queued candidates', async () => {
    const pc = new Peer(), fail = vi.fn(), send = vi.fn(async (packet: { kind: string }) => {
      if (packet.kind === 'ice_candidate') throw new Error('socket closed')
    })
    const flow = new BoardOffer(pc as unknown as RTCPeerConnection, send, fail)
    await flow.start(); pc.emit('candidate:1 1 UDP 1 192.0.2.1 5000 typ host'); pc.emit(null); await flush()
    expect(fail).toHaveBeenCalledWith(expect.objectContaining({ message: 'socket closed' }))
    expect(send).toHaveBeenCalledTimes(2)
  })
})
