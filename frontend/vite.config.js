import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  base: './',
  build: {
    outDir: '../site',
    // NEVER wipe site/ on rebuild: site/data is a live docker bind-mountpoint
    // (data repo's public/) — deleting it orphans the mount and /data/* 404s
    // until the container restarts. Stale hashed assets are the lesser evil.
    emptyOutDir: false,
  },
})
