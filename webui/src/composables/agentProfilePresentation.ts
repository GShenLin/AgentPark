import type { AgentProfile } from '../api'

export function agentProfileDescription(
  profile: Pick<AgentProfile, 'description' | 'profile_metadata'> | null | undefined,
): string {
  return String(profile?.description || profile?.profile_metadata?.description || '').trim()
}
