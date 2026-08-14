/** Vitest — tests unitaires du frontend (D-051). jsdom + RTL pour les composants, `node` pour
 *  la logique pure. L'alias `@` reflète celui de `vite.config.ts` / `tsconfig`. */
import path from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Vitest ne pose `NODE_ENV=test` que s'il est ABSENT. Une image de conteneur qui exporte
// `NODE_ENV=production` (usuel sur les runners) fait donc résoudre React sur son build de
// production, où `act()` n'existe pas : 151 tests sur 215 tombent, pour une raison qui n'est
// nulle part dans le code. On le pose ici, avant toute résolution de module, pour que la suite
// dépende du dépôt et non du shell qui l'appelle.
process.env.NODE_ENV = 'test'

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
