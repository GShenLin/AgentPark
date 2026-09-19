import { computed, ref } from 'vue'
import { getGatewaySettings, updateGatewaySettings, type GatewaySettings } from '../../gatewayApi'
import { t } from '../../i18n'
import { useGatewayModelEditor } from './gatewayModelEditor'

// Own the saved snapshot and all configuration drafts in one place. The model
// form only edits these drafts; only the page toolbar persists them.
export function useGatewaySettingsEditor() {
  const settings = ref<GatewaySettings | null>(null)
  const enabled = ref(false)
  const requireApiKey = ref(true)
  const loading = ref(false)
  const saving = ref(false)
  const error = ref('')
  const status = ref('')
  const models = useGatewayModelEditor([], () => settings.value?.providers || [])
  const dirty = computed(() => settings.value !== null && (
    enabled.value !== settings.value.enabled || requireApiKey.value !== settings.value.requireApiKey || models.dirty.value
  ))

  function accept(snapshot: GatewaySettings) {
    settings.value = snapshot
    enabled.value = snapshot.enabled
    requireApiKey.value = snapshot.requireApiKey
    models.reset(snapshot.models)
  }

  function discard() {
    if (settings.value) accept(settings.value)
    error.value = ''
    status.value = ''
  }

  async function load() {
    if (loading.value || saving.value) return
    loading.value = true
    error.value = ''
    status.value = ''
    try {
      accept(await getGatewaySettings())
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function save(): Promise<boolean> {
    if (!settings.value || loading.value || saving.value) return false
    error.value = ''
    status.value = ''
    try {
      const payload = { enabled: enabled.value, requireApiKey: requireApiKey.value, models: models.prepareModels() }
      saving.value = true
      accept(await updateGatewaySettings(payload))
      status.value = t('gateway.settingsSaved')
      return true
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
      return false
    } finally {
      saving.value = false
    }
  }

  return { settings, enabled, requireApiKey, models, dirty, loading, saving, error, status, load, save, discard }
}
