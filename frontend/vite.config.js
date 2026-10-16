import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// React talks only to Spring Boot (port 8080), never to the ML service.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { '/api': process.env.API_TARGET || 'http://localhost:8080' } },
})
