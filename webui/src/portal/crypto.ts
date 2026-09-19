export const SIGNAL_TTL_SECONDS = 120
export const SIGNAL_CLOCK_SKEW_SECONDS = 5

export function encodeBase64(data: Uint8Array): string {
  let text = ''
  for (let offset = 0; offset < data.length; offset += 16000) text += String.fromCharCode(...data.subarray(offset, offset + 16000))
  return btoa(text)
}
export function decodeBase64(text: string): Uint8Array<ArrayBuffer> {
  return Uint8Array.from(atob(text), c => c.charCodeAt(0))
}
export function canonical(data: Record<string, unknown>): Uint8Array<ArrayBuffer> {
  return new TextEncoder().encode(JSON.stringify(data, Object.keys(data).sort()))
}
export async function publicPeerId(publicKey: string): Promise<string> {
  const bytes = decodeBase64(publicKey)
  if (bytes.length !== 32) throw new Error('Invalid device public key.')
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('')
}
export async function createIdentity() {
  const pair = await crypto.subtle.generateKey({ name: 'Ed25519' }, false, ['sign', 'verify']) as CryptoKeyPair
  const publicKey = encodeBase64(new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey)))
  return {
    publicKey,
    peerId: await publicPeerId(publicKey),
    async sign(body: Record<string, unknown>) {
      return encodeBase64(new Uint8Array(await crypto.subtle.sign('Ed25519', pair.privateKey, canonical(body))))
    },
  }
}
export async function verifySignal(body: Record<string, unknown>, expectedPeer: string, target: string, session: string) {
  if (body.target !== target || body.session_id !== session || body.kind !== 'answer') throw new Error('Device answer does not match this Board session.')
  const expires = Number(body.expires_at)
  const now = Date.now()
  if (!Number.isSafeInteger(expires) || expires * 1000 <= now || expires * 1000 > now + (SIGNAL_TTL_SECONDS + SIGNAL_CLOCK_SKEW_SECONDS) * 1000) throw new Error('Device answer has expired or its clock is out of sync.')
  if (await publicPeerId(String(body.public_key)) !== expectedPeer) throw new Error('Device fingerprint does not match the selected device.')
  const { signature, ...signed } = body
  const key = await crypto.subtle.importKey('raw', decodeBase64(String(body.public_key)), 'Ed25519', false, ['verify'])
  if (!await crypto.subtle.verify('Ed25519', key, decodeBase64(String(signature)), canonical(signed))) throw new Error('Device answer signature is invalid.')
}
