/** Vitest — tests unitaires du frontend (D-051). jsdom + RTL pour les composants, `node` pour
 *  la logique pure. L'alias `@` reflète celui de `vite.config.ts` / `tsconfig`. */
import path from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
