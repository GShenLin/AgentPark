import { inject, onBeforeUnmount, onMounted, ref, type InjectionKey, type Ref } from 'vue'

export interface SettingsNavigation {
  compact: Ref<boolean>
  detailBack: Ref<(() => boolean) | null>
}

export const settingsNavigationKey: InjectionKey<SettingsNavigation> = Symbol('settings-navigation')

export function createSettingsPageNavigation(options: {
  compact: Ref<boolean>
  busy: Ref<boolean>
  hasChanges: Ref<boolean>
  confirmDiscard: () => boolean
  exit: () => void
}) {
  const sectionOpen = ref(false)
  const detailBack = ref<(() => boolean) | null>(null)
  const confirmLeave = () => !options.busy.value
    && (!options.hasChanges.value || options.confirmDiscard())
  const handleBack = () => {
    if (options.busy.value) return
    if (options.compact.value && sectionOpen.value) {
      if (detailBack.value?.()) return
      sectionOpen.value = false
      return
    }
    if (confirmLeave()) options.exit()
  }
  return { sectionOpen, detailBack, confirmLeave, handleBack }
}

export function useCompactSettings() {
  const compact = ref(false)
  let media: MediaQueryList | undefined
  const update = () => { compact.value = Boolean(media?.matches) }
  onMounted(() => {
    media = window.matchMedia('(max-width: 960px)')
    update()
    media.addEventListener('change', update)
  })
  onBeforeUnmount(() => media?.removeEventListener('change', update))
  return compact
}

// Every master/detail panel retains its draft when returning to its list.
export function useSettingsDetail() {
  const detailOpen = ref(false)
  const navigation = inject(settingsNavigationKey, null)
  const openDetail = () => { detailOpen.value = true }
  const closeDetail = () => { detailOpen.value = false }
  const back = () => {
    if (!navigation?.compact.value || !detailOpen.value) return false
    closeDetail()
    return true
  }
  onMounted(() => { if (navigation) navigation.detailBack.value = back })
  onBeforeUnmount(() => {
    if (navigation?.detailBack.value === back) navigation.detailBack.value = null
  })
  return { detailOpen, openDetail, closeDetail }
}
