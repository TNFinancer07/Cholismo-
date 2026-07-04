import type { Config } from 'tailwindcss'

/** Tokens couleur (TASKS 0.3 / CLAUDE §3) — lignée Bloomberg :
 *  fond noir profond, Sony CYAN, Youssef VIOLET, Router OR (bordure/trait, jamais
 *  remplissage), risque VERT/JAUNE/ROUGE toujours doublé d'une forme/icône. */
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
        sony: { DEFAULT: '#22d3ee', dim: '#0e7490' },      // S1 cyan
        youssef: { DEFAULT: '#a78bfa', dim: '#6d28d9' },   // S2 violet
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
