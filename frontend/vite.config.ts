import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend has no CORS middleware, so the dev server proxies `/api/*` to
// FastAPI and strips the prefix. The browser therefore only ever talks to the
// Vite origin.
const BACKEND_URL = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: BACKEND_URL,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
