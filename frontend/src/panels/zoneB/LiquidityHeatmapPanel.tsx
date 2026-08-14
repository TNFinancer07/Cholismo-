/** Panneau HEATMAP LIQUIDITÉ (D-036) — lit UN champ : `s1_state.liquidity_heatmap` (CLAUDE §1).
 *  Diffusion en DELTA (/polish) : le backend émet UNE colonne par tick (4 Hz), le panneau
 *  ACCUMULE la fenêtre glissante dans un tampon local et calcule lui-même la normalisation
 *  couleur — payload allégé ~60×. Rendu HTML5 Canvas (un seul bitmap, aucun nœud DOM par cellule
 *  → tient le 4 Hz sans surcharger le DOM). Temps = X (ancien → récent), prix = Y ; taille au
 *  repos = intensité (bids VERT sous le mid / asks ROUGE au-dessus : côté encodé par couleur ET
 *  position). LECTURE SEULE : aucun affordance de passage d'ordre (§2.1). FAIL-CLOSED (§3) :
 *  périmé → FIGÉ + grisé (tampon conservé) ; absent → tampon vidé + « PAS DE DONNÉES ». */
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { HeatmapColumn } from '@/types/schema'

const GREEN = '52, 211, 153'    // risk-green (bids)
const RED = '248, 113, 113'     // risk-red (asks)
const MAX_COLS = 60             // fenêtre glissante (miroir de HEATMAP_COLS backend) ≈ 15 s à 4 Hz

// intensité → alpha : plancher pour la visibilité des petites tailles, gamma pour le contraste.
function alphaFor(size: number, max: number): number {
  if (!(max > 0) || !Number.isFinite(size) || size <= 0) return 0
  return 0.06 + 0.9 * Math.pow(Math.min(1, size / max), 0.65)
}

function draw(ctx: CanvasRenderingContext2D, cols: HeatmapColumn[], w: number, h: number) {
  ctx.clearRect(0, 0, w, h)
  if (cols.length === 0) return

  // étendue de prix + pas + max de taille (fenêtre entière), calculés côté client.
  let pmin = Infinity, pmax = -Infinity, maxSize = 0
  const uniq = new Set<number>()
  const scan = (levels: [number, number][] | undefined) => {
    if (!Array.isArray(levels)) return
    for (const lvl of levels) {
      const p = lvl?.[0], s = lvl?.[1]
      if (Number.isFinite(p)) { if (p < pmin) pmin = p; if (p > pmax) pmax = p; uniq.add(p) }
      if (Number.isFinite(s) && s > maxSize) maxSize = s
    }
  }
  for (const c of cols) { scan(c?.bids); scan(c?.asks) }
  if (!Number.isFinite(pmin) || pmax <= pmin || !(maxSize > 0)) return

  const sorted = [...uniq].sort((a, b) => a - b)
  let tick = Infinity
  for (let i = 1; i < sorted.length; i++) { const d = sorted[i] - sorted[i - 1]; if (d > 0 && d < tick) tick = d }
  if (!Number.isFinite(tick) || tick <= 0) tick = (pmax - pmin) || 1

  const rows = Math.max(1, Math.round((pmax - pmin) / tick) + 1)
  const rowH = h / rows
  const colW = w / MAX_COLS                       // largeur fixe : la fenêtre défile de droite
  const xBase = w - cols.length * colW            // colonnes calées à DROITE (récent = bord droit)
  const yOf = (p: number) => h - (Math.round((p - pmin) / tick) + 1) * rowH
  const cellW = Math.ceil(colW) + 1, cellH = Math.ceil(rowH) + 1

  for (let j = 0; j < cols.length; j++) {
    const c = cols[j]
    if (!c || !Array.isArray(c.bids) || !Array.isArray(c.asks)) continue
    const x = xBase + j * colW
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
  const bufferRef = useRef<HeatmapColumn[]>([])   // fenêtre glissante accumulée côté client
  const lastTsRef = useRef<number>(-Infinity)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const [colCount, setColCount] = useState(0)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setBox({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  // accumulation du DELTA + dessin (même effet : le tampon est un ref, persistant entre rendus).
  useEffect(() => {
    const fresh = hm?.freshness
    const col = hm?.value?.column
    if (fresh === 'ABSENT') {
      bufferRef.current = []                       // donnée disparue → tampon vidé (§3)
      lastTsRef.current = -Infinity
    } else if (fresh === 'FRESH' && col && Number.isFinite(col.ts) && col.ts > lastTsRef.current) {
      bufferRef.current.push(col)                  // nouvelle colonne (dédup par ts croissant)
      if (bufferRef.current.length > MAX_COLS) bufferRef.current.splice(0, bufferRef.current.length - MAX_COLS)
      lastTsRef.current = col.ts
    }
    if (bufferRef.current.length !== colCount) setColCount(bufferRef.current.length)

    const canvas = canvasRef.current
    if (!canvas || box.w === 0 || box.h === 0) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(box.w * dpr)
    canvas.height = Math.round(box.h * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    draw(ctx, bufferRef.current, box.w, box.h)
  }, [hm, box, colCount])

  const fresh = hm?.freshness
  const noData = colCount === 0

  return (
    <Panel code="HM" title="Heatmap liquidité" block="s1_state.liquidity_heatmap" accent="sony"
      right={<span className="tabular-nums text-xxs text-term-faint">{colCount} col · 4 Hz · delta</span>}>
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
