const { test } = require('node:test')
const assert = require('node:assert/strict')
const { selectProxy, windowsProxy, describeDownloadError } = require('./installer-network.cjs')

test('configured project proxy takes precedence, then environment, npm, and Windows proxy', () => {
  const environment = { HTTPS_PROXY: 'http://env:80', npm_config_https_proxy: 'http://npm:80' }
  const system = () => 'http://system:80'
  assert.equal(selectProxy(environment, { httpProxy: 'http://project:80' }, system).proxy, 'http://project:80')
  assert.equal(selectProxy(environment, {}, system).source, 'environment')
  assert.equal(selectProxy({ npm_config_https_proxy: 'http://npm:80' }, {}, system).proxy, 'http://npm:80')
  assert.equal(selectProxy({}, {}, system).proxy, 'http://system:80')
  assert.equal(selectProxy({}, {}, () => '').source, 'direct')
})

test('reads enabled Windows proxies and uses HTTPS entry from per-protocol settings', () => {
  assert.equal(windowsProxy({ ProxyEnable: 0, ProxyServer: '127.0.0.1:9000' }), '')
  assert.equal(windowsProxy({ ProxyEnable: 1, ProxyServer: '127.0.0.1:9000' }), 'http://127.0.0.1:9000')
  assert.equal(windowsProxy({ ProxyEnable: 1, ProxyServer: 'http=a:80;https=b:81' }), 'http://b:81')
})

test('keeps no-proxy settings and rejects invalid configuration without exposing credentials', () => {
  assert.equal(selectProxy({ HTTPS_PROXY: 'http://proxy:80', NO_PROXY: '*.internal' }, {}, () => '').noProxy, '*.internal')
  assert.equal(selectProxy({}, { httpProxy: 'http://proxy:80', noProxy: 'internal' }, () => '').noProxy, 'internal')
  assert.throws(() => selectProxy({}, { httpProxy: 10 }, () => ''), /must be strings/)
  assert.throws(() => selectProxy({}, { httpProxy: 'socks5://proxy:80' }, () => ''), /HTTP\(S\)/)
})

test('download diagnostics retain underlying causes and redact proxy credentials', () => {
  const cause = Object.assign(new Error('connect failed for http://user:secret@proxy:80'), { code: 'ECONNREFUSED' })
  const error = new TypeError('fetch failed', { cause: new AggregateError([cause]) })
  const message = describeDownloadError(error)
  assert.match(message, /ECONNREFUSED/)
  assert.match(message, /fetch failed/)
  assert.ok(!message.includes('secret'))
})

test('upstream Electron fetch actually connects through the configured proxy', { timeout: 20000 }, async () => {
  const http = require('node:http')
  const { spawn } = require('node:child_process')
  const fs = require('node:fs'), os = require('node:os'), path = require('node:path')
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'node-window-network-'))
  const proxy = http.createServer()
  let connections = 0
  proxy.on('connect', (_request, socket) => {
    connections++
    socket.end('HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
  })
  await new Promise(resolve => proxy.listen(0, '127.0.0.1', resolve))
  try {
    const source = `
      const {configureInstallerNetwork,describeDownloadError}=require('./installer-network.cjs');
      configureInstallerNetwork({configPath:process.env.TEST_CONFIG_PATH});
      require('node:diagnostics_channel').channel('undici:request:error').subscribe(({error})=>console.error(describeDownloadError(error)));
      const {downloadArtifact}=require('@electron/get');
      downloadArtifact({version:'44.7.0',artifactName:'electron',platform:'win32',arch:'x64',
        cacheRoot:process.env.TEST_CACHE,force:true,
        mirrorOptions:{mirror:'https://electron-download.invalid/'}}).then(()=>process.exit(2)).catch(error=>{
          console.error(describeDownloadError(error)); process.exitCode=1;
        });`
    const result = await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, ['-e', source], { cwd: __dirname, windowsHide: true,
        env: { ...process.env, HTTPS_PROXY: `http://127.0.0.1:${proxy.address().port}`,
          https_proxy: `http://127.0.0.1:${proxy.address().port}`, NO_PROXY: 'localhost', no_proxy: 'localhost',
          TEST_CONFIG_PATH: path.join(temporary, 'absent.json'), TEST_CACHE: path.join(temporary, 'cache') } })
      let output = ''
      child.stdout.on('data', value => { output += value })
      child.stderr.on('data', value => { output += value })
      const timeout = setTimeout(() => child.kill(), 15000)
      child.on('error', reject)
      child.on('close', code => { clearTimeout(timeout); resolve({ code, output }) })
    })
    assert.equal(result.code, 1, result.output)
    assert.equal(connections, 1, result.output)
    assert.match(result.output, /environment proxy/)
    assert.match(result.output, /403|aborted|canceled|cancelled/i)
  } finally {
    await new Promise(resolve => proxy.close(resolve))
    fs.rmSync(temporary, { recursive: true, force: true })
  }
})
