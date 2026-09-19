import { getActiveApiBase, requestApiJson } from './api'

export interface PeerGrant {
  peer_id: string
  name: string
  view: boolean
  control: boolean
  collaborate: boolean
  graph_ids: string[]
}
export interface PeerInfo extends PeerGrant { state: string; error: string }
export interface PeerSettings {
  enabled: boolean
  server_ip: string
  display_name: string
}
export interface PeerStatus {
  peer_id: string
  settings: PeerSettings
  peers: PeerInfo[]
  coordinator_connected: boolean
  error: string
  enrollment_state: 'disconnected' | 'pending' | 'approved' | 'rejected'
  device_name: string
}
export interface PeerNode { id: string; name: string; state: string; pending_count: number }
export interface PeerConversation { text: string; live_message: string; history_complete: boolean; state: string }

export function peerApi<T>(path = '', method = 'GET', payload?: unknown): Promise<T> {
  // Mutations intentionally have no automatic network retries.
  return requestApiJson(getActiveApiBase(), `/api/peers${path}`, {
    method, ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  }) as Promise<T>
}
export function callPeer<T>(peer: string, call: Record<string, unknown>): Promise<T> {
  return peerApi<T>(`/${encodeURIComponent(peer)}/call`, 'POST', call)
}
