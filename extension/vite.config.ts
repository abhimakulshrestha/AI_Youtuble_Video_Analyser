import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { fileURLToPath } from 'url'
import { readFileSync, writeFileSync } from 'fs'

const projectDir = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig(({ mode }) => ({
  // Chrome needs a host permission for the API origin chosen at build time.
  plugins: [react(), {
    name: 'api-host-permission',
    closeBundle() {
      const apiBase = loadEnv(mode, projectDir, 'VITE_').VITE_API_BASE_URL
      if (!apiBase) return
      const origin = new URL(apiBase).origin
      const manifestPath = resolve(projectDir, 'dist/manifest.json')
      const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
      const permission = `${origin}/*`
      manifest.host_permissions = manifest.host_permissions.filter((host: string) =>
        !host.startsWith('http://127.0.0.1:8000/') && !host.startsWith('http://localhost:8000/')
      )
      if (!manifest.host_permissions.includes(permission)) manifest.host_permissions.push(permission)
      writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n')
    }
  }],
  build: {
    rollupOptions: {
      input: {
        sidepanel: resolve(projectDir, 'index.html'),
        background: resolve(projectDir, 'src/background.ts'),
        content: resolve(projectDir, 'src/content/youtube-content.ts')
      },
      output: {
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].[hash].js',
        assetFileNames: 'assets/[name].[hash].[ext]'
      }
    }
  }
}))
