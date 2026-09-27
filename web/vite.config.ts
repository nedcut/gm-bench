import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// BASE_PATH is set by the Pages workflow to "/<repo>/" for project pages;
// local dev and preview keep the root default.
// One HTML entry per page: GitHub Pages has no SPA fallback, so every URL the
// site links to must exist as a real file.
export default defineConfig({
  base: process.env.BASE_PATH ?? '/',
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        home: resolve(__dirname, 'index.html'),
        results: resolve(__dirname, 'results/index.html'),
        replays: resolve(__dirname, 'replays/index.html'),
        protocol: resolve(__dirname, 'protocol/index.html'),
      },
    },
  },
})
