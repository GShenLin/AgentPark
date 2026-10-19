import { configDefaults, defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

const voiceUi = 'src/voice/workspaceVoice.test.ts'
const nodeWindowUi = 'tests/nodeWindowConversation.test.ts'
export default mergeConfig(viteConfig, defineConfig({
  test: {
    projects: [
      { extends: true, test: { name: 'unit', exclude: [...configDefaults.exclude, voiceUi, nodeWindowUi] } },
      { extends: true, test: { name: 'voice-ui', include: [voiceUi], environment: './src/voice/rendererTestEnvironment.ts' } },
      { extends: true, test: { name: 'node-window-ui', include: [nodeWindowUi], environment: './src/voice/rendererTestEnvironment.ts' } },
    ],
  },
}))
