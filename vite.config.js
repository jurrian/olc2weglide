import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vitejs.dev/config/
export default defineConfig({
  base: './',
  plugins: [
    vue(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    proxy: {
      '/api/fetch_flights': {
        target: 'http://localhost:${VITE_API_PORT}',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api\/fetch_flights/, '/fetch_flights')
      },
      '/api/upload_status': {
        target: 'http://localhost:${VITE_API_PORT}',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api\/upload_status/, '/upload_status')
      },
      '/api/upload_flights': {
        target: 'http://localhost:${VITE_API_PORT}',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api\/upload_flights/, '/upload_flights')
      },
      '/api/find_gliders': {
        target: 'http://localhost:${VITE_API_PORT}',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api\/find_gliders/, '/find_gliders')
      },
      '/api/status': {
        target: 'http://localhost:${VITE_API_PORT}',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api\/status/, '/status')
      }
    }
  }
})
