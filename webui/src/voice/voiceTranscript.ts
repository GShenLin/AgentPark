import type { VoiceEvent } from './voiceProtocol'

export type VoiceTranscriptLine = {
  role: 'user' | 'assistant'; text: string; offset_ms: number; incomplete: boolean
}
export type VoiceFinish = {
  status: 'ended' | 'error'; duration_ms: number; lines: VoiceTranscriptLine[]
}

/** Keep all turns, including the last unfinished caption, in arrival order. */
export class VoiceTranscript {
  private readonly started = performance.now()
  private readonly lines: VoiceTranscriptLine[] = []
  private readonly pending = new Map<VoiceTranscriptLine['role'], VoiceTranscriptLine>()

  add(event: Extract<VoiceEvent, { kind: 'transcript' }>) {
    let line = this.pending.get(event.role)
    if (!line) {
      line = { role: event.role, text: '', offset_ms: this.elapsed(), incomplete: true }
      this.lines.push(line)
      this.pending.set(event.role, line)
    }
    if (event.done) {
      // A done event replaces its deltas instead of duplicating the turn.
      if (event.text) line.text = event.text
      line.incomplete = false
      this.pending.delete(event.role)
    } else line.text = (event.replace ? '' : line.text) + event.text
  }

  finish(status: VoiceFinish['status']): VoiceFinish {
    return { status, duration_ms: this.elapsed(), lines: this.lines.filter(line => line.text.length > 0).map(line => ({ ...line })) }
  }

  interrupt(role?: VoiceTranscriptLine['role']) {
    // Retain unfinished turns as incomplete, so a new response cannot overwrite them.
    if (role) this.pending.delete(role)
    else this.pending.clear()
  }

  private elapsed() { return Math.max(0, Math.round(performance.now() - this.started)) }
}
