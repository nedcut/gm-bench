import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// BASE_PATH is set by the Pages workflow to "/<repo>/" for project pages;
// local dev and preview keep the root default.
export default defineConfig({
  base: process.env.BASE_PATH ?? '/',
  plugins: [react()],
})
