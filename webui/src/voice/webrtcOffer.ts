/** HTTP SDP exchange has no trickle-ICE route: include gathered candidates. */
export async function completeVoiceOffer(pc: RTCPeerConnection, signal: AbortSignal): Promise<string> {
  await pc.setLocalDescription(await pc.createOffer())
  if (signal.aborted) throw new Error('语音连接已取消。')
  if (pc.iceGatheringState !== 'complete') {
    await new Promise<void>((resolve, reject) => {
      const finish = (error?: Error) => {
        clearTimeout(timer)
        pc.removeEventListener('icegatheringstatechange', changed)
        signal.removeEventListener('abort', aborted)
        error ? reject(error) : resolve()
      }
      const changed = () => { if (pc.iceGatheringState === 'complete') finish() }
      const aborted = () => finish(new Error('语音连接已取消。'))
      const timer = setTimeout(() => finish(new Error('收集语音连接地址超时，请检查网络。')), 10_000)
      pc.addEventListener('icegatheringstatechange', changed)
      signal.addEventListener('abort', aborted, { once: true })
      changed()
    })
  }
  if (!pc.localDescription?.sdp) throw new Error('未生成语音连接信息。')
  return pc.localDescription.sdp
}
