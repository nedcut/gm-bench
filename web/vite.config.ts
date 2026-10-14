import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { simulatorBundle } from './scripts/simulatorBundle.ts'

// BASE_PATH is set by the Pages workflow to "/<repo>/" for project pages;
// local dev and preview keep the root default.
// One HTML entry per page: GitHub Pages has no SPA fallback, so every URL the
// site links to must exist as a real file.
export default defineConfig({
  base: process.env.BASE_PATH ?? '/',
  plugins: [simulatorBundle(), react()],
  optimizeDeps: { include: ['pyodide'] },
  build: {
    rollupOptions: {
      input: {
        standings: resolve(__dirname, 'index.html'),
        how: resolve(__dirname, 'how-it-works/index.html'),
        cost: resolve(__dirname, 'cost/index.html'),
        tools: resolve(__dirname, 'tools/index.html'),
        play: resolve(__dirname, 'play/index.html'),
        replays: resolve(__dirname, 'replays/index.html'),
        method: resolve(__dirname, 'method/index.html'),
        v1: resolve(__dirname, 'v1/index.html'),
      },
    },
  },
})
