import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const workspaceDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const workspaceConfigPath = path.join(workspaceDir, 'config', 'config.json')

function loadServerOrigin(): string {
  const raw = fs.readFileSync(workspaceConfigPath, 'utf-8')
  const payload = JSON.parse(raw)
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('config/config.json must contain a top-level object.')
  }
  const server = payload.server
  if (!server || typeof server !== 'object' || Array.isArray(server)) {
    throw new Error("config/config.json field 'server' must be an object.")
  }
  const host = String(server.host || '').trim() || '127.0.0.1'
  const port = Number.parseInt(String(server.port ?? ''), 10)
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new Error("config/config.json field 'server.port' must be between 1 and 65535.")
  }
  const proxyHost = host === '0.0.0.0' || host === '::' ? '127.0.0.1' : host
  return `http://${proxyHost}:${port}`
}

const serverOrigin = loadServerOrigin()

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: serverOrigin,
        changeOrigin: true,
      },
      '/memories': {
        target: serverOrigin,
        changeOrigin: true,
      },
    },
  },
})
