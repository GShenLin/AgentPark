const { channel } = require('node:diagnostics_channel')
const { configureInstallerNetwork, describeDownloadError } = require('./installer-network.cjs')

// Observe the upstream fetch client, retaining its installer, TLS validation,
// checksum verification, cache and extraction behavior.
channel('undici:request:error').subscribe(({ request, error }) => {
  const destination = new URL(request.origin).hostname
  console.error(`[ERROR] Electron download from ${destination}: ${describeDownloadError(error)}`)
})
configureInstallerNetwork()
require('./node_modules/electron/install.js')
