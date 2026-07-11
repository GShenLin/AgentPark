export function applyResponsesApiDefaults(provider: Record<string, unknown>) {
  if (provider.toolResultSubmissionMaxChars === undefined || provider.toolResultSubmissionMaxChars === null || provider.toolResultSubmissionMaxChars === '') {
    provider.toolResultSubmissionMaxChars = 50000
  }
  if (provider.toolContextCompactionEnabled === undefined || provider.toolContextCompactionEnabled === null) {
    provider.toolContextCompactionEnabled = false
  }
  if (provider.toolContextCompactionEveryToolCalls === undefined || provider.toolContextCompactionEveryToolCalls === null || provider.toolContextCompactionEveryToolCalls === '') {
    provider.toolContextCompactionEveryToolCalls = 30
  }
  if (String(provider.type || '').trim().toLowerCase() === 'openai' && typeof provider.responsesReplayReasoningItems !== 'boolean') {
    provider.responsesReplayReasoningItems = false
  }
}
