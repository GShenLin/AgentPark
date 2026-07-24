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
  if (provider.toolContextCompactionInputTokens === undefined || provider.toolContextCompactionInputTokens === null || provider.toolContextCompactionInputTokens === '') {
    provider.toolContextCompactionInputTokens = 0
  }
  if (provider.toolContextCompactionOutputTokens === undefined || provider.toolContextCompactionOutputTokens === null || provider.toolContextCompactionOutputTokens === '') {
    provider.toolContextCompactionOutputTokens = 0
  }
  if (String(provider.type || '').trim().toLowerCase() === 'openai' && typeof provider.responsesReplayReasoningItems !== 'boolean') {
    provider.responsesReplayReasoningItems = false
  }
}
