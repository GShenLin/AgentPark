import type { InjectionKey, Ref } from 'vue'
import type { AgentPanelSettings } from '../agentPanelSettings'

export const conversationWindowSettings: InjectionKey<Ref<AgentPanelSettings>> = Symbol('conversation-window-settings')
