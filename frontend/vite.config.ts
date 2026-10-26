import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import { resolveDevServerSettings } from './vite.env.ts'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // loadEnv combina process.env y .env.<mode> (solo variables VITE_*)
  const { port, proxyTarget } = resolveDevServerSettings(loadEnv(mode, process.cwd(), 'VITE_'))
  return {
    plugins: [react()],
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test-setup.ts'],
    },
    server: {
      host: true,
      port,
      allowedHosts: true,
      proxy: {
        '/api': proxyTarget,
      },
    },
  }
})
