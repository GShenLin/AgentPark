import { createIdentity, verifySignal, SIGNAL_TTL_SECONDS } from './crypto'
import { BrowserPeerRpc } from './rpc'
import { connectionLabel, parseIceLease } from './ice'
import { BoardOffer } from './BoardOffer'

export async function connectBoard(target: string, stunUrls: string[], onDisconnect: (error: string) => void, signal?: AbortSignal) {
  signal?.throwIfAborted()
  if (!window.isSecureContext || !crypto.subtle) throw new Error('Cloud Board requires HTTPS or a loopback development address.')
  if (stunUrls.some(url => !url.startsWith('stun:'))) throw new Error('Invalid STUN discovery address.')
  const identity = await createIdentity()
  const session = crypto.randomUUID().replace(/-/g, '')
  const pc = new RTCPeerConnection({ iceServers: stunUrls.map(urls => ({ urls })), iceTransportPolicy: 'all' })
  const channel = pc.createDataChannel('agentpark.v1', { ordered: true })
  const rpc = new BrowserPeerRpc(channel)
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/portal/connect`)
  let cleanupRequested = false
  let established = false
  let rejectReady: (reason: Error) => void = () => {}
  const closed = () => { if (!cleanupRequested) fail(new Error('连接已断开，请重新打开设备 Board。')) }
  const fail = (error: Error) => {
    if (cleanupRequested) return
    cleanupRequested = true
    rejectReady(error); if (established) onDisconnect(error.message)
    offer.close(); rpc.close(); pc.close(); ws.close()
  }
  const offer = new BoardOffer(pc, async packet => {
    if (cleanupRequested) return
    const body = { ...packet, target, session_id: session, public_key: identity.publicKey,
      expires_at: Math.floor(Date.now() / 1000) + SIGNAL_TTL_SECONDS }
    const signature = await identity.sign(body)
    if (!cleanupRequested) ws.send(JSON.stringify({ ...body, signature }))
  }, fail)
  const connected = new Promise<void>((resolve, reject) => {
    rejectReady = reject
    channel.onopen = () => { established = true; resolve() }
    channel.onclose = closed
    ws.onerror = () => fail(new Error('Unable to connect to the cloud portal. Check your login session.'))
    ws.onclose = () => { if (!cleanupRequested) fail(new Error('Cloud Board session ended. Sign in and reopen the Board.')) }
    pc.onconnectionstatechange = () => { if (pc.connectionState === 'failed') fail(new Error(`设备连接失败（${offer.diagnostic()}）。`)) }
  })
  ws.onmessage = event => {
    void (async () => {
      const packet = JSON.parse(String(event.data))
      if (packet.kind === 'challenge') {
        ws.send(JSON.stringify({ public_key: identity.publicKey, signature: await identity.sign({ challenge: packet.challenge }) }))
      } else if (packet.kind === 'ready') {
        if (packet.peer_id !== identity.peerId) throw new Error('Browser identity acknowledgement mismatch.')
        if (packet.board_protocol !== 'trickle-ice-v1') throw new Error('云端连接服务版本过旧，请更新鉴权服务器。')
        const lease = parseIceLease(packet.ice)
        pc.setConfiguration({ iceServers: [...stunUrls.map(urls => ({ urls })), ...lease.ice_servers], iceTransportPolicy: 'all' })
        await offer.start()
      } else if (packet.kind === 'signal') {
        await verifySignal(packet.signal, target, identity.peerId, session)
        await pc.setRemoteDescription({ type: 'answer', sdp: packet.signal.sdp })
      } else if (packet.kind === 'error') throw new Error(String(packet.error))
      else throw new Error('Unknown portal signaling packet.')
    })().catch(cause => fail(cause instanceof Error ? cause : new Error(String(cause))))
  }
  let timeout: ReturnType<typeof setTimeout> | undefined
  const abort = () => { cleanupRequested = true; rejectReady(new DOMException('Board connection cancelled.', 'AbortError')) }
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) abort()
  try {
    await Promise.race([connected, new Promise<never>((_resolve, reject) => { timeout = setTimeout(() => reject(new Error(`设备连接超时（${offer.diagnostic()}）。`)), 40000) })])
  } catch (error) { cleanupRequested = true; offer.close(); rpc.close(); pc.close(); ws.close(); throw error }
  finally { if (timeout) clearTimeout(timeout); signal?.removeEventListener('abort', abort) }
  return { rpc, async describeTransport() { return connectionLabel(await pc.getStats()) },
    close() { cleanupRequested = true; offer.close(); rpc.close(); pc.close(); ws.close() } }
}
