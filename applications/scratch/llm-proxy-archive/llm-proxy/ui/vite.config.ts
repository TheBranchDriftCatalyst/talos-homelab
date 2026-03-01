import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/_/ui/',  // Serve UI at /_/ui/ path
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      // Proxy WebSocket and API to Go backend
      '/ws': {
        target: 'http://localhost:8080',
        ws: true,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/ws/, '/_/ws'),
      },
      '/_/': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: true,
      },
      '/health': 'http://localhost:8080',
      '/metrics': 'http://localhost:8080',
    },
  },
})
