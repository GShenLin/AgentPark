export function isCloudPortal(): boolean {
  return typeof document !== 'undefined' && document.querySelector('meta[name="agentpark-portal"]') !== null
}

export function isCloudBoard(): boolean {
  return isCloudPortal() && /^\/board\/[a-f0-9]{64}$/.test(window.location.pathname)
}
