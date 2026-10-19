import { inject, onBeforeUnmount } from 'vue'
import { getActiveApiBase } from '../api'
import { attachmentResource, type MessageAttachment, type MessageResource } from '../composables/messageAttachments'
import type { VoiceTarget } from '../voiceApi'
import { workspaceVoiceKey } from './workspaceVoice'

export type VoiceComposerSnapshot = { text: string; resources: MessageResource[] }
export type VoiceComposerEdit = { expected_text: string; text: string }
type Composer = { target: VoiceTarget; text: string; attachments: MessageAttachment[]; uploading: boolean; locked: boolean }

/** Readers belong to the workspace and only expose the matching, mounted composer. */
export function createVoiceComposers() {
  const readers = new Map<() => Composer | null, (text: string) => void>()
  function resolve(target: VoiceTarget) {
    const matches = [...readers].map(([read, write]) => ({ composer: read(), write })).filter(({ composer }) => composer
      && composer.target.base === target.base && composer.target.graph === target.graph && composer.target.node === target.node)
    if (!matches.length) throw new Error('请先打开当前通话节点的聊天输入框。')
    if (matches.length !== 1) throw new Error('当前节点有多个输入框，请只保留一个后重试。')
    const { composer, write } = matches[0]!
    if (!composer) throw new Error('当前输入框已关闭。')
    if (composer.uploading) throw new Error('输入框附件尚在上传，请等上传完成后重试。')
    if (composer.text.length > 128000 || composer.attachments.length > 32) throw new Error('一次操作最多支持 128000 字符和 32 个附件，请减少输入框内容后重试。')
    return { composer, write }
  }
  function snapshot(composer: Composer): VoiceComposerSnapshot {
    return { text: composer.text, resources: composer.attachments.map(file => attachmentResource(file, 'voice_composer')) }
  }
  return {
    register(read: () => Composer | null, write: (text: string) => void) { readers.set(read, write); return () => readers.delete(read) },
    read(target: VoiceTarget): VoiceComposerSnapshot {
      return snapshot(resolve(target).composer)
    },
    edit(target: VoiceTarget, edit: VoiceComposerEdit): VoiceComposerSnapshot {
      if (typeof edit.expected_text !== 'string' || typeof edit.text !== 'string'
          || edit.expected_text.length > 128000 || edit.text.length > 128000) throw new Error('草稿修改参数无效或超过 128000 字符。')
      const { composer, write } = resolve(target)
      if (composer.locked) throw new Error('输入框正在发送，请稍后重新读取并修改。')
      if (composer.text !== edit.expected_text) throw new Error('输入框内容已变化，未做修改。请重新读取草稿，保留用户的新内容后再修改。')
      // Compare and write synchronously: typing cannot interleave with this edit.
      const result = snapshot({ ...composer, text: edit.text })
      write(edit.text)
      return result
    },
  }
}

export function useVoiceComposer(read: () => Omit<Composer, 'target'> & { node: string; graph: string } | null, write: (text: string) => void) {
  const workspace = inject(workspaceVoiceKey, null)
  const unregister = workspace?.composers.register(() => {
    const value = read()
    return value ? { ...value, target: { base: getActiveApiBase(), graph: value.graph, node: value.node } } : null
  }, write)
  onBeforeUnmount(() => unregister?.())
}
