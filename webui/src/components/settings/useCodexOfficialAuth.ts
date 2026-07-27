import { onBeforeUnmount, ref } from 'vue'
import { getProviderAuthStatus, startProviderLogin, submitProviderLoginCode, type CodexAuthStatus } from '../../settingsApi'


export function useCodexOfficialAuth() {
  const status = ref<CodexAuthStatus | null>(null)
  const busy = ref(false)
  const error = ref('')
  let statusTimer = 0
  let activeProvider = 'openai'

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

  async function loadStatus(provider = activeProvider) {
    activeProvider = provider
    try {
      const next = await getProviderAuthStatus(provider)
      if (provider === activeProvider) {
        status.value = next
        error.value = ''
      }
    } catch (loadError) {
      if (provider === activeProvider) {
        error.value = String((loadError as Error)?.message || loadError)
      }
    }
  }

  async function beginLogin(provider = activeProvider) {
    activeProvider = provider
    const loginWindow = window.open('about:blank', '_blank')
    busy.value = true
    error.value = ''
    try {
      await loadStatus(provider)
      const login = await startProviderLogin(provider)
      if (loginWindow) {
        loginWindow.opener = null
        loginWindow.location.href = login.authUrl
        startStatusPolling()
        if (login.manualCode) {
          const code = window.prompt('完成 Claude 登录后，如页面显示授权码，请粘贴授权码或最终跳转 URL：')
          if (code?.trim()) {
            status.value = await submitProviderLoginCode(provider, code.trim())
            stopStatusPolling()
          }
        }
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

  function setStatus(value: CodexAuthStatus) {
    status.value = value
  }

  return { status, busy, error, loadStatus, beginLogin, setStatus }
}
