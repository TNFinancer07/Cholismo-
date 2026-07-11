import type { Config } from 'tailwindcss'

/** Tokens couleur (TASKS 0.3 / CLAUDE §3, D-024) — fond noir profond, Sony ROUGE
 *  framboise, Youssef JAUNE citron (teintes DISTINCTES des statuts de risque : rouge
 *  saumon / ambre), Router OR (bordure/trait, jamais remplissage). La couleur opérateur
 *  n'est JAMAIS seule : chaque bloc porte un badge texte S1 · SONY / S2 · YOUSSEF ;
 *  le risque VERT/JAUNE/ROUGE reste toujours doublé d'une forme/icône. */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        term: {
          bg: '#06080b',        // Bloomberg-black
          panel: '#0b0f15',
          panel2: '#0e141c',
          border: '#1c2633',
          grid: '#141b25',
          text: '#c9d4e3',
          dim: '#67788f',
          faint: '#3d4a5c',
        },
        sony: { DEFAULT: '#f43f5e', dim: '#9f1239' },      // S1 ROUGE framboise (≠ risque #f87171 saumon)
        youssef: { DEFAULT: '#facc15', dim: '#854d0e' },   // S2 JAUNE citron (≠ risque #fbbf24 ambre, ≠ Router or)
        router: { DEFAULT: '#f0b429', dim: '#92610e' },    // OR — bordure/trait uniquement
        risk: {
          green: '#34d399',
          yellow: '#fbbf24',
          red: '#f87171',
        },
        stale: '#8b96a5',
        absent: '#f87171',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        xxs: ['0.65rem', { lineHeight: '0.9rem' }],
      },
    },
  },
  plugins: [],
} satisfies Config
