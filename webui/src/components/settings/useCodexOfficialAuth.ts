import { onBeforeUnmount, ref } from 'vue'
import { getCodexAuthStatus, startCodexLogin, type CodexAuthStatus } from '../../settingsApi'


export function useCodexOfficialAuth() {
  const status = ref<CodexAuthStatus | null>(null)
  const busy = ref(false)
  const error = ref('')
  let statusTimer = 0

  function stopStatusPolling() {
    if (statusTimer) window.clearInterval(statusTimer)
    statusTimer = 0
  }

  function startStatusPolling() {
    stopStatusPolling()
    let attempts = 0
    statusTimer = window.setInterval(async () => {
      attempts += 1
      await loadStatus()
      if (status.value?.authorized || attempts >= 60) stopStatusPolling()
    }, 2000)
  }

  async function loadStatus() {
    try {
      status.value = await getCodexAuthStatus()
      error.value = ''
    } catch (loadError) {
      error.value = String((loadError as Error)?.message || loadError)
    }
  }

  async function beginLogin() {
    const loginWindow = window.open('about:blank', '_blank')
    busy.value = true
    error.value = ''
    try {
      await loadStatus()
      if (status.value?.authorized) {
        loginWindow?.close()
        return
      }
      const login = await startCodexLogin()
      if (loginWindow) {
        loginWindow.opener = null
        loginWindow.location.href = login.authUrl
        startStatusPolling()
      } else {
        error.value = '浏览器阻止了登录窗口，请允许弹出窗口后重试。'
      }
    } catch (loginError) {
      loginWindow?.close()
      error.value = String((loginError as Error)?.message || loginError)
    } finally {
      busy.value = false
    }
  }

  onBeforeUnmount(stopStatusPolling)

  return { status, busy, error, loadStatus, beginLogin }
}
