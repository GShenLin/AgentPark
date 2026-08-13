function formatUuidV4(bytes: Uint8Array) {
  const versionByte = bytes[6]
  const variantByte = bytes[8]
  if (bytes.length !== 16 || versionByte === undefined || variantByte === undefined) {
    throw new Error('UUID generation requires exactly 16 random bytes.')
  }
  bytes[6] = (versionByte & 0x0f) | 0x40
  bytes[8] = (variantByte & 0x3f) | 0x80

  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0'))
  return [
    hex.slice(0, 4).join(''),
    hex.slice(4, 6).join(''),
    hex.slice(6, 8).join(''),
    hex.slice(8, 10).join(''),
    hex.slice(10, 16).join(''),
  ].join('-')
}

export function createBrowserUuid() {
  const browserCrypto = globalThis.crypto
  if (typeof browserCrypto?.randomUUID === 'function') {
    return browserCrypto.randomUUID()
  }
  if (typeof browserCrypto?.getRandomValues !== 'function') {
    throw new Error('This browser cannot generate cryptographically secure IDs.')
  }

  return formatUuidV4(browserCrypto.getRandomValues(new Uint8Array(16)))
}
