const ACCESS_CLIENT_ID_KEY = 'agentpark.accessClientId'
const ACCESS_USERNAME_KEY = 'agentpark.accessUsername'
let volatileClientId = ''
let volatileUsername = ''

function storageValue(key: string) {
  try {
    const stored = window.localStorage.getItem(key) || ''
    if (stored) return stored
  } catch {
    // Fall through to the session-local value.
  }
  return key === ACCESS_CLIENT_ID_KEY ? volatileClientId : volatileUsername
}

function setStorageValue(key: string, value: string) {
  if (key === ACCESS_CLIENT_ID_KEY) volatileClientId = value
  if (key === ACCESS_USERNAME_KEY) volatileUsername = value
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // The current page continues with the session-local value.
  }
}

export function getAccessClientId() {
  let clientId = storageValue(ACCESS_CLIENT_ID_KEY).trim()
  if (!clientId) {
    clientId = typeof crypto?.randomUUID === 'function'
      ? crypto.randomUUID()
      : `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`
    setStorageValue(ACCESS_CLIENT_ID_KEY, clientId)
  }
  return clientId
}

export function getAccessUsername() {
  return storageValue(ACCESS_USERNAME_KEY).trim()
}

export function setAccessUsername(username: string) {
  const value = String(username || '').trim()
  if (value) setStorageValue(ACCESS_USERNAME_KEY, value)
}

export function syncCanonicalAccessUsername(username: string) {
  const value = String(username || '').trim()
  if (value && value !== getAccessUsername()) setStorageValue(ACCESS_USERNAME_KEY, value)
}

export function accessRequestHeaders() {
  const clientId = getAccessClientId()
  const username = getAccessUsername()
  return {
    'X-AgentPark-Client-Id': clientId,
    ...(username ? { 'X-AgentPark-Username': username } : {}),
  }
}
