/** Panneau HEATMAP LIQUIDITÉ (D-036) — lit UN champ : `s1_state.liquidity_heatmap` (CLAUDE §1).
 *  Rend la profondeur HISTORIQUE du carnet L2 en HTML5 Canvas (haute performance : un seul
 *  bitmap, aucun nœud DOM par cellule → tient le 4 Hz sans surcharger le DOM). Temps = axe X
 *  (ancien → récent), prix = axe Y ; taille au repos = intensité (bids VERT sous le mid, asks
 *  ROUGE au-dessus — le côté est encodé par la couleur ET la position). LECTURE SEULE : aucun
 *  affordance de passage d'ordre (§2.1). FAIL-CLOSED (§3) : périmé → FIGÉ + grisé ; absent/vide
 *  → « PAS DE DONNÉES », jamais une profondeur inventée. */
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { HeatmapValue } from '@/types/schema'

const GREEN = '52, 211, 153'    // risk-green (bids)
const RED = '248, 113, 113'     // risk-red (asks)

// intensité → alpha : plancher pour la visibilité des petites tailles, gamma pour le contraste.
function alphaFor(size: number, max: number): number {
  if (!(max > 0) || !Number.isFinite(size) || size <= 0) return 0
  return 0.06 + 0.9 * Math.pow(Math.min(1, size / max), 0.65)
}

function draw(ctx: CanvasRenderingContext2D, value: HeatmapValue | null | undefined, w: number, h: number) {
  ctx.clearRect(0, 0, w, h)
  const cols = value?.columns ?? []
  const maxSize = value?.max_size ?? 0
  if (cols.length === 0 || !(maxSize > 0)) return

  // étendue de prix + pas (plus petit écart positif entre prix adjacents → hauteur de cellule).
  let pmin = Infinity, pmax = -Infinity
  const uniq = new Set<number>()
  const scan = (levels: [number, number][] | undefined) => {
    if (!Array.isArray(levels)) return
    for (const lvl of levels) {
      const p = lvl?.[0]
      if (Number.isFinite(p)) { if (p < pmin) pmin = p; if (p > pmax) pmax = p; uniq.add(p) }
    }
  }
  for (const c of cols) { scan(c?.bids); scan(c?.asks) }
  if (!Number.isFinite(pmin) || pmax <= pmin) return
  const sorted = [...uniq].sort((a, b) => a - b)
  let tick = Infinity
  for (let i = 1; i < sorted.length; i++) { const d = sorted[i] - sorted[i - 1]; if (d > 0 && d < tick) tick = d }
  if (!Number.isFinite(tick) || tick <= 0) tick = (pmax - pmin) || 1

  const rows = Math.max(1, Math.round((pmax - pmin) / tick) + 1)
  const rowH = h / rows
  const colW = w / cols.length
  const yOf = (p: number) => h - (Math.round((p - pmin) / tick) + 1) * rowH
  const cellW = Math.ceil(colW) + 1, cellH = Math.ceil(rowH) + 1

  for (let j = 0; j < cols.length; j++) {
    const c = cols[j]
    if (!c || !Array.isArray(c.bids) || !Array.isArray(c.asks)) continue   // colonne malformée → ignorée
    const x = j * colW
    for (const [p, s] of c.bids) {
      if (!Number.isFinite(p)) continue
      const a = alphaFor(s, maxSize); if (a <= 0) continue
      ctx.fillStyle = `rgba(${GREEN}, ${a})`; ctx.fillRect(x, yOf(p), cellW, cellH)
    }
    for (const [p, s] of c.asks) {
      if (!Number.isFinite(p)) continue
      const a = alphaFor(s, maxSize); if (a <= 0) continue
      ctx.fillStyle = `rgba(${RED}, ${a})`; ctx.fillRect(x, yOf(p), cellW, cellH)
    }
  }

  // ligne de mid discrète (dernière colonne) — repère d'orientation, jamais un signal.
  const last = cols[cols.length - 1]
  const bb = last?.bids?.[0]?.[0], ba = last?.asks?.[0]?.[0]
  if (Number.isFinite(bb) && Number.isFinite(ba)) {
    const y = h - (((bb + ba) / 2 - pmin) / tick) * rowH
    if (Number.isFinite(y)) {
      ctx.strokeStyle = 'rgba(201, 212, 227, 0.25)'; ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke()
    }
  }
}

export function LiquidityHeatmapPanel() {
  const hm = useTerminal((s) => s.s1_state?.liquidity_heatmap)
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setBox({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || box.w === 0 || box.h === 0) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(box.w * dpr)
    canvas.height = Math.round(box.h * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    draw(ctx, hm?.value, box.w, box.h)
  }, [hm, box])

  const fresh = hm?.freshness
  const cols = hm?.value?.columns ?? []
  const noData = fresh === 'ABSENT' || cols.length === 0

  return (
    <Panel code="HM" title="Heatmap liquidité" block="s1_state.liquidity_heatmap" accent="sony"
      right={<span className="tabular-nums text-xxs text-term-faint">{cols.length} col · 4 Hz</span>}>
      <div ref={wrapRef} className={cn('relative h-full w-full', fresh === 'STALE' && 'opacity-60')}>
        <canvas ref={canvasRef} className="block h-full w-full" />
        {noData && (
          <div className="absolute inset-0 grid place-items-center">
            <span className="absent-pulse font-mono text-xs font-bold text-absent">PAS DE DONNÉES</span>
          </div>
        )}
        {fresh === 'STALE' && (
          <span className="absolute right-1 top-1 border border-stale/50 px-1 text-xxs font-bold text-stale">FIGÉ</span>
        )}
      </div>
    </Panel>
  )
}
