import type { Environment } from 'vitest/environments'

// Compile Vue templates for the client while the test supplies its own renderer.
export default {
  name: 'voice-renderer',
  viteEnvironment: 'client',
  setup: () => ({ teardown() {} }),
} satisfies Environment
