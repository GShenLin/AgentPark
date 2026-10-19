const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')
const { createRequire } = require('node:module')

function windowsProxy(value) {
  if (!value?.ProxyEnable || !value.ProxyServer) return ''
  const raw = String(value.ProxyServer).trim()
  const entries = Object.fromEntries(raw.split(';').filter(item => item.includes('=')).map(item => {
    const index = item.indexOf('=')
    return [item.slice(0, index).trim().toLowerCase(), item.slice(index + 1).trim()]
  }))
  const selected = raw.includes('=') ? entries.https || entries.http || '' : raw
  return selected && !selected.includes('://') ? `http://${selected}` : selected
}

function readWindowsProxy() {
  // Read only the existing user proxy; never modify OS settings or execute PAC.
  const script = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); $k=Get-ItemProperty -LiteralPath 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' -ErrorAction Stop; @{ProxyEnable=$k.ProxyEnable;ProxyServer=$k.ProxyServer}|ConvertTo-Json -Compress"
  return windowsProxy(JSON.parse(execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    encoding: 'utf8', windowsHide: true, timeout: 10000,
  }).replace(/^\uFEFF/, '')))
}

function selectProxy(env, network, getWindowsProxy) {
  const project = network.httpProxy
  const projectBypass = network.noProxy
  for (const value of [project, projectBypass]) {
    if (value !== undefined && value !== null && typeof value !== 'string') throw new Error('Project network proxy settings must be strings.')
  }
  let source = 'direct'
  const environment = env.https_proxy || env.HTTPS_PROXY || env.http_proxy || env.HTTP_PROXY || env.all_proxy || env.ALL_PROXY
  const npm = env.npm_config_https_proxy || env.npm_config_proxy
  const proxy = project?.trim() || environment || npm || getWindowsProxy()
  if (proxy) {
    source = project?.trim() ? 'project' : environment ? 'environment' : npm ? 'npm' : 'Windows system'
    let url
    try { url = new URL(proxy) } catch { throw new Error('Invalid Electron proxy URL in the configured network settings.') }
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname) throw new Error('Electron download requires an HTTP(S) proxy URL.')
  }
  return { proxy, source, noProxy: projectBypass?.trim() || env.no_proxy || env.NO_PROXY || env.npm_config_noproxy || 'localhost,127.0.0.1,::1' }
}

function configureInstallerNetwork({ configPath = path.resolve(__dirname, '../../config/config.json') } = {}) {
  const config = fs.existsSync(configPath) ? JSON.parse(fs.readFileSync(configPath, 'utf8').replace(/^\uFEFF/, '')) : {}
  if (config.network != null && (typeof config.network !== 'object' || Array.isArray(config.network))) throw new Error('Project network settings must be an object.')
  const selected = selectProxy(process.env, config.network || {}, () => process.platform === 'win32' ? readWindowsProxy() : '')
  if (selected.proxy) {
    // Validate the upstream proxy dependency explicitly; upstream otherwise hides
    // a missing optional undici package and attempts a direct connection.
    const electronRequire = createRequire(require.resolve('electron/package.json'))
    const getRequire = createRequire(electronRequire.resolve('@electron/get'))
    getRequire('undici')
    process.env.HTTP_PROXY = process.env.http_proxy = selected.proxy
    process.env.HTTPS_PROXY = process.env.https_proxy = selected.proxy
    process.env.NO_PROXY = process.env.no_proxy = selected.noProxy
    process.env.ELECTRON_GET_USE_PROXY = '1'
  }
  console.log(`[INFO] Electron download network: ${selected.source}${selected.proxy ? ' proxy' : ''}`)
}

function describeDownloadError(error) {
  const messages = [], visited = new Set()
  function visit(current) {
    if (!current || visited.has(current)) return
    visited.add(current)
    const message = String(current.message || current).replace(/(https?:\/\/)[^\s/@]+@/g, '$1[redacted]@')
    messages.push(`${current.code ? `${current.code}: ` : ''}${message}`)
    visit(current.cause)
    if (Array.isArray(current.errors)) current.errors.forEach(visit)
  }
  visit(error)
  return messages.join(' -> ')
}

module.exports = { configureInstallerNetwork, selectProxy, windowsProxy, describeDownloadError }
