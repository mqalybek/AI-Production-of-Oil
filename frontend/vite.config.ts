import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// В проде фронтенд и API стоят за одним reverse-proxy на одном домене
// (/api/*), поэтому в dev-режиме прокси имитирует ту же схему — код
// одинаково обращается к '/api/...' в обоих случаях.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
