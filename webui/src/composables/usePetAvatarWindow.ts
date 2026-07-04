import { onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

type PetWindowBridge = {
  hideWindow?: (viewId: string) => Promise<unknown>
  moveWindowBy?: (deltaX: number, deltaY: number) => Promise<unknown>
  setWindowLayout?: (viewId: string, payload: { expanded: boolean; menu: boolean; bubble: boolean; bubbleHeight: number }) => Promise<unknown>
}

type PetAvatarWindowOptions = {
  viewId: string
  menuOpen: Ref<boolean>
  bubbleOpen: Ref<boolean>
  bubbleHeight: Ref<number>
}

type PetWindowLayoutOverride = {
  expanded?: boolean
  menu?: boolean
  bubble?: boolean
}

const DRAG_CLICK_THRESHOLD = 4

function getPetBridge(): PetWindowBridge | null {
  const bridge = (window as unknown as { agentParkPet?: PetWindowBridge }).agentParkPet
  return bridge && typeof bridge === 'object' ? bridge : null
}

export function usePetAvatarWindow(options: PetAvatarWindowOptions) {
  const chatOpen = ref(false)
  let draggingPointerId = -1
  let startScreenX = 0
  let startScreenY = 0
  let lastScreenX = 0
  let lastScreenY = 0
  let movedDuringDrag = false

  async function syncPetWindowLayout(override: PetWindowLayoutOverride = {}) {
    const bridge = getPetBridge()
    if (!bridge || typeof bridge.setWindowLayout !== 'function') return null
    const expanded = override.expanded ?? chatOpen.value
    const menu = override.menu ?? options.menuOpen.value
    const bubble = override.bubble ?? options.bubbleOpen.value
    return bridge.setWindowLayout(options.viewId, {
      expanded,
      menu: menu && !expanded,
      bubble: bubble && !expanded && !menu,
      bubbleHeight: options.bubbleHeight.value,
    })
  }

  async function hidePetWindow(viewId: string) {
    const bridge = getPetBridge()
    if (!bridge || typeof bridge.hideWindow !== 'function') return false
    await bridge.hideWindow(viewId)
    return true
  }

  function collapsePetPanel() {
    chatOpen.value = false
    options.menuOpen.value = false
  }

  function openChatPanel() {
    options.menuOpen.value = false
    chatOpen.value = true
  }

  function moveWindowBy(deltaX: number, deltaY: number) {
    if (deltaX === 0 && deltaY === 0) return
    const bridge = getPetBridge()
    if (!bridge || typeof bridge.moveWindowBy !== 'function') return
    void bridge.moveWindowBy(deltaX, deltaY)
  }

  function finishAvatarDrag(target: EventTarget | null) {
    if (draggingPointerId < 0) return
    if (target instanceof HTMLElement && typeof target.releasePointerCapture === 'function') {
      try {
        target.releasePointerCapture(draggingPointerId)
      } catch {
        // The pointer may already be released by the browser.
      }
    }
    window.removeEventListener('pointermove', onAvatarPointerMove)
    window.removeEventListener('pointerup', onAvatarPointerUp)
    const shouldOpenChat = !movedDuringDrag
    draggingPointerId = -1
    movedDuringDrag = false
    if (shouldOpenChat) openChatPanel()
  }

  function onAvatarPointerMove(event: PointerEvent) {
    if (event.pointerId !== draggingPointerId) return
    const totalX = event.screenX - startScreenX
    const totalY = event.screenY - startScreenY
    if (Math.abs(totalX) > DRAG_CLICK_THRESHOLD || Math.abs(totalY) > DRAG_CLICK_THRESHOLD) {
      movedDuringDrag = true
    }
    const deltaX = event.screenX - lastScreenX
    const deltaY = event.screenY - lastScreenY
    lastScreenX = event.screenX
    lastScreenY = event.screenY
    moveWindowBy(deltaX, deltaY)
  }

  function onAvatarPointerUp(event: PointerEvent) {
    if (event.pointerId !== draggingPointerId) return
    finishAvatarDrag(event.target)
  }

  function onAvatarPointerDown(event: PointerEvent) {
    if (event.button !== 0) return
    event.preventDefault()
    options.menuOpen.value = false
    draggingPointerId = event.pointerId
    startScreenX = event.screenX
    startScreenY = event.screenY
    lastScreenX = event.screenX
    lastScreenY = event.screenY
    movedDuringDrag = false
    if (event.currentTarget instanceof HTMLElement && typeof event.currentTarget.setPointerCapture === 'function') {
      event.currentTarget.setPointerCapture(event.pointerId)
    }
    window.addEventListener('pointermove', onAvatarPointerMove)
    window.addEventListener('pointerup', onAvatarPointerUp)
  }

  function onWindowBlur() {
    collapsePetPanel()
  }

  watch([chatOpen, options.menuOpen, options.bubbleOpen, options.bubbleHeight], () => {
    void syncPetWindowLayout()
  })

  onMounted(() => {
    window.addEventListener('blur', onWindowBlur)
    void syncPetWindowLayout()
  })

  onBeforeUnmount(() => {
    window.removeEventListener('blur', onWindowBlur)
    window.removeEventListener('pointermove', onAvatarPointerMove)
    window.removeEventListener('pointerup', onAvatarPointerUp)
  })

  return {
    chatOpen,
    collapsePetPanel,
    hidePetWindow,
    onAvatarPointerDown,
    openChatPanel,
    syncPetWindowLayout,
  }
}
