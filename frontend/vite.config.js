import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  base: './',
  build: {
    outDir: '../site',
    emptyOutDir: true, // site/ is pure build output; runtime data/ is volume-mounted
  },
})
