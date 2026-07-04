import { onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

type PetWindowBridge = {
  hideWindow?: (viewId: string) => Promise<unknown>
  log?: (event: string, payload: Record<string, unknown>) => Promise<unknown>
  moveWindowBy?: (deltaX: number, deltaY: number) => Promise<unknown>
  setWindowLayout?: (viewId: string, payload: PetWindowLayoutPayload) => Promise<unknown>
}

export type PetPanelSize = {
  width: number
  height: number
}

type PetWindowLayoutPayload = {
  expanded: boolean
  menu: boolean
  bubble: boolean
  bubbleHeight: number
  panelSize?: PetPanelSize | null
  resizeAnchor?: string
}

type PetAvatarWindowOptions = {
  viewId: string
  menuOpen: Ref<boolean>
  menuLayoutOpen?: Readonly<Ref<boolean>>
  bubbleOpen: Ref<boolean>
  bubbleHeight: Ref<number>
  panelSize?: Ref<PetPanelSize | null>
}

type PetWindowLayoutOverride = {
  expanded?: boolean
  menu?: boolean
  bubble?: boolean
  panelSize?: PetPanelSize | null
  resizeAnchor?: string
}

const DRAG_CLICK_THRESHOLD = 4

function getPetBridge(): PetWindowBridge | null {
  const bridge = (window as unknown as { agentParkPet?: PetWindowBridge }).agentParkPet
  return bridge && typeof bridge === 'object' ? bridge : null
}

function logPetWindowDiagnostic(event: string, payload: Record<string, unknown> = {}) {
  const bridge = getPetBridge()
  if (bridge && typeof bridge.log === 'function') {
    void bridge.log(event, payload).catch((exc) => {
      console.warn('[AgentParkPetRenderer] failed to write window diagnostic log', exc)
    })
  }
}

function plainPanelSize(value: PetPanelSize | null | undefined): PetPanelSize | null {
  if (!value) return null
  const width = Number(value.width)
  const height = Number(value.height)
  if (!Number.isFinite(width) || !Number.isFinite(height)) return null
  return { width, height }
}

export function usePetAvatarWindow(options: PetAvatarWindowOptions) {
  const chatOpen = ref(false)
  const wantsExpandedLayout = ref(false)
  const menuLayoutOpen = options.menuLayoutOpen ?? options.menuOpen
  let draggingPointerId = -1
  let startScreenX = 0
  let startScreenY = 0
  let lastScreenX = 0
  let lastScreenY = 0
  let movedDuringDrag = false
  let suppressBlurUntil = 0

  function suppressBlurCollapse(durationMs = 900) {
    suppressBlurUntil = Math.max(suppressBlurUntil, Date.now() + durationMs)
  }

  async function syncPetWindowLayout(override: PetWindowLayoutOverride = {}) {
    const bridge = getPetBridge()
    if (!bridge || typeof bridge.setWindowLayout !== 'function') return null
    suppressBlurCollapse()
    const expanded = override.expanded ?? wantsExpandedLayout.value
    const menu = override.menu ?? menuLayoutOpen.value
    const bubble = override.bubble ?? options.bubbleOpen.value
    const panelSize = plainPanelSize(override.panelSize ?? options.panelSize?.value)
    const payload = {
      expanded,
      menu: menu && !expanded,
      bubble: bubble && !expanded && !menu,
      bubbleHeight: options.bubbleHeight.value,
      panelSize,
      resizeAnchor: String(override.resizeAnchor || ''),
    }
    logPetWindowDiagnostic('window-layout-request', {
      viewId: options.viewId,
      override: {
        expanded: override.expanded,
        menu: override.menu,
        bubble: override.bubble,
        panelSize: plainPanelSize(override.panelSize),
        resizeAnchor: override.resizeAnchor,
      },
      state: {
        chatOpen: chatOpen.value,
        wantsExpandedLayout: wantsExpandedLayout.value,
        menuLayoutOpen: menuLayoutOpen.value,
        menuOpen: options.menuOpen.value,
        bubbleOpen: options.bubbleOpen.value,
      },
      payload,
      viewport: { width: window.innerWidth, height: window.innerHeight },
    })
    try {
      const result = await bridge.setWindowLayout(options.viewId, payload)
      logPetWindowDiagnostic('window-layout-result', {
        viewId: options.viewId,
        result: result && typeof result === 'object' ? result as Record<string, unknown> : { value: result },
        viewport: { width: window.innerWidth, height: window.innerHeight },
      })
      return result
    } catch (exc) {
      logPetWindowDiagnostic('window-layout-error', {
        viewId: options.viewId,
        message: exc instanceof Error ? exc.message : String(exc || ''),
        stack: exc instanceof Error ? exc.stack : '',
      })
      throw exc
    }
  }

  function waitForAnimationFrame() {
    return new Promise<void>((resolve) => {
      window.requestAnimationFrame(() => resolve())
    })
  }

  async function hidePetWindow(viewId: string) {
    const bridge = getPetBridge()
    if (!bridge || typeof bridge.hideWindow !== 'function') return false
    await bridge.hideWindow(viewId)
    return true
  }

  function collapsePetPanel() {
    wantsExpandedLayout.value = false
    chatOpen.value = false
    options.menuOpen.value = false
  }

  async function openChatPanel() {
    suppressBlurCollapse(1500)
    wantsExpandedLayout.value = true
    options.menuOpen.value = false
    chatOpen.value = true
    await syncPetWindowLayout({ expanded: true, menu: false, bubble: false })
    await waitForAnimationFrame()
    suppressBlurCollapse(700)
    void syncPetWindowLayout({ expanded: true, menu: false, bubble: false })
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
    if (shouldOpenChat) void openChatPanel()
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
    if (Date.now() < suppressBlurUntil) return
    collapsePetPanel()
  }

  watch([wantsExpandedLayout, chatOpen, menuLayoutOpen, options.bubbleOpen, options.bubbleHeight], () => {
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
