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
    // VIZ-10: vendors en chunks propios (equivalente de `manualChunks` en Rolldown, el empaquetador de Vite 8).
    // React cambia poco y queda cacheado; recharts (y sus dependencias d3) solo baja con las vistas de gráficos.
    build: {
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [
              { name: 'vendor-react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 20 },
              { name: 'vendor-charts', test: /node_modules[\\/](recharts|d3-[^\\/]+|victory-vendor|es-toolkit|immer|reselect|redux|@reduxjs|react-redux|use-sync-external-store|decimal\.js-light|eventemitter3|tiny-invariant|clsx)[\\/]/, priority: 10 },
            ],
          },
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test-setup.ts'],
      // MET-01: solo se mide con `--coverage` (`npm run test:coverage`, lo usa la CI). Sin umbrales: es reporte.
      coverage: {
        provider: 'v8',
        reporter: ['text-summary', 'json-summary', 'lcov'],
        reportsDirectory: 'coverage',
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/test-setup.ts', 'src/main.tsx', 'src/**/*.d.ts'],
      },
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
