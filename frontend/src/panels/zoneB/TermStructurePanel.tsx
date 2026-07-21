/** Panneau VTS — Term Structure de volatilité (D-039) — lit UN champ : `vol_surface.term_structure`
 *  (CLAUDE §1). Trace la courbe VIX9D/VIX/VIX3M/VIX6M (x = échéance en jours, y = niveau) en HTML5
 *  Canvas, avec un badge d'ÉTAT : CONTANGO (pente ↗, régime normal) / BACKWARDATION (pente ↘,
 *  stress) / FLAT — état encodé par TEXTE + glyphe + couleur (jamais la couleur seule §3). Advisory
 *  (§2.1). LECTURE SEULE. FAIL-CLOSED (§3) : périmé → FIGÉ ; < 2 points → « PAS DE DONNÉES ». */
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { TermPoint, TermStructureValue } from '@/types/schema'

const LINE = '148, 163, 184'   // gris-bleu lisible (état indéterminé / FLAT)
const GOLD = '240, 180, 41'
const GREEN = '52, 211, 153', RED = '248, 113, 113'   // contango / backwardation
const R = Math.round

function draw(canvas: HTMLCanvasElement, val: TermStructureValue | null | undefined, box: { w: number; h: number }) {
  const dpr = window.devicePixelRatio || 1
  const W = box.w, H = box.h
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px'
  canvas.width = R(W * dpr); canvas.height = R(H * dpr)
  const ctx = canvas.getContext('2d'); if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H)
  // /devil : ne garde que les points ENTIÈREMENT finis → pas de NaN dans l'étendue ni de
  // `.toFixed` sur une valeur absente (fail-closed §3).
  const pts: TermPoint[] = (Array.isArray(val?.points) ? val!.points : [])
    .filter((p) => p && Number.isFinite(p.value) && Number.isFinite(p.days))
  if (W < 4 || H < 4 || pts.length < 2) return

  const days = pts.map((p) => p.days), vals = pts.map((p) => p.value)
  const dmin = Math.min(...days), dmax = Math.max(...days)
  let vmin = Math.min(...vals), vmax = Math.max(...vals)
  if (vmax - vmin < 1e-6) { vmax += 1; vmin -= 1 }
  const PL = 26, PR = 8, PT = 10, PB = 16
  const xOf = (d: number) => PL + (dmax === dmin ? 0 : ((d - dmin) / (dmax - dmin)) * (W - PL - PR))
  const yOf = (v: number) => PT + ((vmax - v) / (vmax - vmin)) * (H - PT - PB)

  // axes min/max
  ctx.font = '8px "JetBrains Mono", ui-monospace, monospace'; ctx.fillStyle = '#67788f'
  ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
  ctx.fillText(vmax.toFixed(0), PL - 3, R(yOf(vmax)) + 4)
  ctx.fillText(vmin.toFixed(0), PL - 3, R(yOf(vmin)) - 4)

  // courbe — teintée selon l'ÉTAT (contango vert / backwardation rouge / plat gris) : renfort du
  // badge, jamais la couleur seule (§3 : le badge texte+glyphe ET la pente réelle portent l'état)
  const state = val?.state
  const curve = state === 'CONTANGO' ? GREEN : state === 'BACKWARDATION' ? RED : LINE
  ctx.strokeStyle = `rgb(${curve})`; ctx.lineWidth = 1.75; ctx.beginPath()
  pts.forEach((p, i) => { const x = xOf(p.days), y = yOf(p.value); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
  ctx.stroke()
  // points + libellés ténor/valeur
  ctx.textBaseline = 'alphabetic'
  pts.forEach((p) => {
    const x = R(xOf(p.days)), y = R(yOf(p.value))
    ctx.fillStyle = `rgb(${GOLD})`; ctx.beginPath(); ctx.arc(x, y, 2.2, 0, 7); ctx.fill()
    ctx.fillStyle = '#c9d4e3'; ctx.textAlign = 'center'
    ctx.fillText(p.value.toFixed(1), x, y - 5)
    ctx.fillStyle = '#67788f'; ctx.fillText(p.tenor ?? '', x, H - 4)
  })
}

export function TermStructurePanel() {
  const ts = useTerminal((s) => s.vol_surface?.term_structure)
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el); setBox({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    if (canvasRef.current) draw(canvasRef.current, ts?.value, box)
  }, [ts, box])

  const fresh = ts?.freshness
  const val = ts?.value
  const pts = (Array.isArray(val?.points) ? val!.points : [])
    .filter((p) => p && Number.isFinite(p.value) && Number.isFinite(p.days))
  const noData = fresh === 'ABSENT' || pts.length < 2
  const state = val?.state ?? null
  const spread = val?.front_back_spread
  const badge = state === 'CONTANGO'
    ? { cls: 'border-risk-green/50 text-risk-green', txt: '↗ CONTANGO' }
    : state === 'BACKWARDATION'
      ? { cls: 'border-risk-red/50 text-risk-red', txt: '↘ BACKWARDATION' }
      : state === 'FLAT'
        ? { cls: 'border-term-border text-term-dim', txt: '→ FLAT' }
        : { cls: 'border-term-border text-term-faint', txt: '— indéterminé' }

  return (
    <Panel code="VTS" title="Term structure vol" block="vol_surface.term_structure" accent="sony"
      right={<span className="tabular-nums text-xxs text-term-faint">
        {typeof spread === 'number' && Number.isFinite(spread) ? `spread ${spread > 0 ? '+' : ''}${spread.toFixed(1)}` : ''}</span>}>
      <div className={cn('flex h-full min-h-0 flex-col gap-0.5', fresh === 'STALE' && 'opacity-60')}>
        <div className={cn('shrink-0 self-start border px-1 text-xxs font-bold', badge.cls)}
          title="État de la structure de vol (advisory §2.1) : CONTANGO normal, BACKWARDATION = stress">
          {badge.txt}
        </div>
        <div ref={wrapRef} className="relative min-h-0 flex-1">
          <canvas ref={canvasRef} className="block" />
          {noData && (
            <div className="absolute inset-0 grid place-items-center">
              <span className="absent-pulse font-mono text-xs font-bold text-absent">PAS DE DONNÉES</span>
            </div>
          )}
          {fresh === 'STALE' && (
            <span className="absolute right-1 top-1 border border-stale/50 px-1 text-xxs font-bold text-stale">FIGÉ</span>
          )}
        </div>
      </div>
    </Panel>
  )
}
