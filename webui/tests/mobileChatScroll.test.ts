import { effectScope, nextTick, ref, shallowRef, watch } from 'vue'
import { describe, expect, it } from 'vitest'
import { useMobileChatScroll } from '../src/mobile/useMobileChatScroll'

function container(height = 600) {
  let top = 0
  return {
    scrollHeight: height, clientHeight: 600,
    get scrollTop() { return top },
    set scrollTop(value: number) { top = Math.max(0, Math.min(value, this.scrollHeight - this.clientHeight)) },
  } as HTMLElement
}

function setup() {
  const scope = effectScope()
  const feed = shallowRef<HTMLElement | null>(null)
  const selection = ref('local:default:Agent')
  const ready = ref(false)
  const height = ref(600)
  scope.run(() => {
    useMobileChatScroll(feed, selection, ready, [height])
    // Model DOM height changing after pre-flush watchers, during rendering.
    watch(height, value => {
      if (feed.value) Object.assign(feed.value, { scrollHeight: value })
    }, { flush: 'post' })
  })
  return { scope, feed, selection, ready, height }
}

describe('mobile chat scroll position', () => {
  it('opens a long conversation at the end when its response arrives', async () => {
    const state = setup()
    state.feed.value = container()
    await nextTick()
    state.height.value = 20000
    state.ready.value = true
    await nextTick()
    await nextTick()
    expect(state.feed.value.scrollTop).toBe(19400)
    state.scope.stop()
  })

  it('opens at the end when the feed mounts after data or remounts', async () => {
    const state = setup()
    state.ready.value = true
    await nextTick()
    state.feed.value = container(20000)
    await nextTick()
    expect(state.feed.value.scrollTop).toBe(19400)
    state.feed.value = null
    await nextTick()
    state.feed.value = container(30000)
    await nextTick()
    expect(state.feed.value.scrollTop).toBe(29400)
    state.scope.stop()
  })

  it('follows a large new reply but preserves scrolling up through history', async () => {
    const state = setup()
    state.feed.value = container(20000)
    state.ready.value = true
    await nextTick()
    state.height.value = 25000
    await nextTick()
    await nextTick()
    expect(state.feed.value.scrollTop).toBe(24400)
    state.feed.value.scrollTop = 1000
    state.height.value = 30000
    await nextTick()
    await nextTick()
    expect(state.feed.value.scrollTop).toBe(1000)
    state.selection.value = 'local:default:Other'
    await nextTick()
    expect(state.feed.value.scrollTop).toBe(29400)
    state.scope.stop()
  })
})
