import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const TARGET = 'https://artifex-production-ba8f.up.railway.app'
const WS_TARGET = 'wss://artifex-production-ba8f.up.railway.app'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: TARGET, changeOrigin: true },
      '/foster': { target: TARGET, changeOrigin: true },
      '/swarm': { target: TARGET, changeOrigin: true },
      '/workflow': {
        target: TARGET,
        changeOrigin: true,
        ws: true,
      },
      '/emergent': { target: TARGET, changeOrigin: true },
      '/health': { target: TARGET, changeOrigin: true },
      '/chat': { target: TARGET, changeOrigin: true },
      '/events': { target: TARGET, changeOrigin: true },
      '/agent': { target: TARGET, changeOrigin: true },
      '/dashboard': { target: TARGET, changeOrigin: true },
      '/families': { target: TARGET, changeOrigin: true },
      '/metrics': { target: TARGET, changeOrigin: true },
      '/ws': {
        target: WS_TARGET,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
