import { computed, type Ref } from 'vue'
import type { SettingsSectionInfo } from '../../settingsApi'

export const DEFAULT_SETTINGS_SECTIONS: SettingsSectionInfo[] = [
  {
    id: 'model-provider',
    label: 'modelProvider',
    path: 'config/modelProvider.json',
    filename: 'modelProvider.json',
  },
  {
    id: 'defaults',
    label: 'Default settings',
    path: 'config/config.json',
    filename: 'config.json',
  },
  {
    id: 'companion',
    label: 'Companion',
    path: 'memories/companion/config.json',
    filename: 'config.json',
  },
  {
    id: 'events',
    label: 'Runtime Events',
    path: 'config/events.json',
    filename: 'events.json',
  },
]

export const SECTION_MESSAGE_KEYS: Record<string, string> = {
  authorization: 'settings.authorization',
  'model-provider': 'settings.modelProvider',
  gateway: 'settings.gateway',
  harness: 'settings.harness',
  defaults: 'settings.defaults',
  companion: 'settings.companion',
  events: 'settings.runtimeEvents',
  'provider-test': 'settings.providerTest',
  pressure: 'settings.pressure',
  'tool-stats': 'settings.statistics',
  'node-profiler-editor': 'settings.nodeProfiler',
  exit: 'settings.exit',
  theme: 'settings.theme',
}

export function useSettingsSections(sections: Ref<SettingsSectionInfo[]>) {
  return computed<SettingsSectionInfo[]>(() => {
    const base = sections.value.slice()
    base.push({ id: 'harness', label: 'Harness', path: '', filename: '' })
    base.push({ id: 'knowledge', label: 'Knowledge', path: '本地文件夹知识库', filename: '' })
    base.push({ id: 'skills', label: 'Skill 管理', path: '项目 · 用户 · 自定义加载路径', filename: '' })
    base.push({ id: 'peer-network', label: '设备互联', path: '', filename: '' })
    base.push({ id: 'node-sync', label: '节点同步', path: '', filename: '' })
    if (!base.some((item) => item.id === 'authorization')) {
      base.unshift({
        id: 'authorization',
        label: 'Authorization',
        path: '.auth/access-control.json',
        filename: 'access-control.json',
      })
    }
    if (!base.some((item) => item.id === 'gateway')) {
      base.splice(Math.min(1, base.length), 0, {
        id: 'gateway',
        label: 'Gateway',
        path: 'config/publicGateway.json · .auth/gateway/keys.json',
        filename: 'publicGateway.json',
      })
    }
    if (!base.some((item) => item.id === 'provider-test')) {
      base.push({
        id: 'provider-test',
        label: 'Test',
        path: 'config/ProviderLimit.json',
        filename: 'ProviderLimit.json',
      })
    }
    if (!base.some((item) => item.id === 'pressure')) {
      base.push({
        id: 'pressure',
        label: 'Pressure',
        path: 'config/modelProvider.json',
        filename: '',
      })
    }
    if (!base.some((item) => item.id === 'tool-stats')) {
      base.push({
        id: 'tool-stats',
        label: 'Static',
        path: '.cache/tool_stats',
        filename: 'summary.json',
      })
    }
    if (!base.some((item) => item.id === 'node-profiler-editor')) {
      base.push({
        id: 'node-profiler-editor',
        label: 'NodeProfilerEditor',
        path: 'agent/*.json',
        filename: '*.json',
      })
    }
    if (!base.some((item) => item.id === 'exit')) {
      base.push({
        id: 'exit',
        label: 'Exit',
        path: 'AgentPark backend',
        filename: '',
      })
    }
    return base
  })
}
