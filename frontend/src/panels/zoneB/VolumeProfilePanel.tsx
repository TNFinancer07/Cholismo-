/** Panneau VP — Volume Profile dynamique (D-041) — lit UN champ : `s1_state.volume_profile`
 *  (CLAUDE §1). Histogramme HORIZONTAL en HTML5 Canvas : axe Y = PRIX (haut = haut), axe X =
 *  VOLUME (barres vers la droite). Surbrillance STRICTE : Value Area (bande sky), POC (barre +
 *  ligne OR), niveaux de la VEILLE (prev POC/VAH/VAL, tiretés violets), Low Volume Nodes (◄ ambre).
 *  Chaque repère = couleur + glyphe/position + libellé (jamais la couleur seule §3). LECTURE SEULE
 *  (§2.1). FAIL-CLOSED (§3) : périmé → FIGÉ ; vide → « PAS DE DONNÉES ». */
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { VolumeProfileValue } from '@/types/schema'

const GOLD = '240, 180, 41', SKY = '56, 189, 248', VIOLET = '167, 139, 250', AMBER = '251, 191, 36'
const PAD_L = 44, PAD_R = 8, PAD_T = 6, PAD_B = 6
const R = Math.round

function draw(canvas: HTMLCanvasElement, vp: VolumeProfileValue | null | undefined, box: { w: number; h: number }) {
  const dpr = window.devicePixelRatio || 1
  const W = box.w, H = box.h
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px'
  canvas.width = R(W * dpr); canvas.height = R(H * dpr)
  const ctx = canvas.getContext('2d'); if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H)
  const levels = (Array.isArray(vp?.levels) ? vp!.levels : []).filter(
    (l) => l && Number.isFinite(l.price) && Number.isFinite(l.volume))
  if (W < 4 || H < 4 || levels.length === 0) return

  let pmin = Infinity, pmax = -Infinity, maxVol = 0
  for (const l of levels) {
    if (l.price < pmin) pmin = l.price; if (l.price > pmax) pmax = l.price
    if (l.volume > maxVol) maxVol = l.volume
  }
  if (!(pmax > pmin) || !(maxVol > 0)) return
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B
  const yOf = (price: number) => PAD_T + ((pmax - price) / (pmax - pmin)) * plotH
  const rowH = Math.max(1, plotH / levels.length)
  const barW = (v: number) => Math.max(0, (v / maxVol) * plotW)
  const tick = vp?.tick && vp.tick > 0 ? vp.tick : 0.25

  // bande Value Area (VAL → VAH) — « valeur » = repère neutre sky (position + libellé aussi)
  if (Number.isFinite(vp?.vah) && Number.isFinite(vp?.val)) {
    const y0 = R(yOf(vp!.vah!) - rowH / 2), y1 = R(yOf(vp!.val!) + rowH / 2)
    ctx.fillStyle = `rgba(${SKY}, 0.09)`; ctx.fillRect(PAD_L, y0, plotW, Math.max(1, y1 - y0))
  }

  // barres de volume (dans la VA = plus vives ; POC = OR)
  const inVA = (p: number) => Number.isFinite(vp?.vah) && Number.isFinite(vp?.val) && p <= vp!.vah! && p >= vp!.val!
  const isPoc = (p: number) => Number.isFinite(vp?.poc) && Math.abs(p - vp!.poc!) < tick / 2
  for (const l of levels) {
    const y = R(yOf(l.price) - rowH / 2), h = Math.max(1, R(rowH) - (rowH > 3 ? 1 : 0))
    ctx.fillStyle = isPoc(l.price) ? `rgba(${GOLD}, 0.9)` : inVA(l.price) ? 'rgba(201, 212, 227, 0.85)' : 'rgba(103, 120, 143, 0.7)'
    ctx.fillRect(PAD_L, y, R(barW(l.volume)), h)
  }

  // ligne POC (OR, pleine) + libellé prix
  const hline = (price: number, color: string, dash: number[], label: string) => {
    if (!Number.isFinite(price)) return
    const yc = Math.max(pmin, Math.min(pmax, price))       // borné à la plage visible
    const y = R(yOf(yc)) + 0.5
    ctx.strokeStyle = `rgb(${color})`; ctx.lineWidth = 1; ctx.setLineDash(dash)
    ctx.beginPath(); ctx.moveTo(PAD_L, y); ctx.lineTo(W - PAD_R, y); ctx.stroke(); ctx.setLineDash([])
    ctx.font = '8px "JetBrains Mono", ui-monospace, monospace'; ctx.fillStyle = `rgb(${color})`
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
    ctx.fillText(label, W - PAD_R - 1, y - 4)
  }
  // veille (violet tireté) — projection des niveaux de la session précédente
  const prev = vp?.previous
  if (prev) {
    hline(prev.val as number, VIOLET, [2, 2], 'yVAL')
    hline(prev.vah as number, VIOLET, [2, 2], 'yVAH')
    hline(prev.poc as number, VIOLET, [4, 2], 'yPOC')
  }
  hline(vp?.poc as number, GOLD, [], 'POC')

  // LVN (creux) — marqueur ◄ ambre à gauche + petite étiquette prix
  ctx.font = '8px "JetBrains Mono", ui-monospace, monospace'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
  for (const p of (Array.isArray(vp?.lvn) ? vp!.lvn : [])) {
    if (!Number.isFinite(p) || p < pmin || p > pmax) continue
    ctx.fillStyle = `rgb(${AMBER})`; ctx.fillText('◄', PAD_L + 1, R(yOf(p)))
  }

  // échelle prix (gouttière gauche) : haut / POC / bas
  ctx.fillStyle = '#67788f'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
  ctx.fillText(pmax.toFixed(2), PAD_L - 3, PAD_T + 5)
  ctx.fillText(pmin.toFixed(2), PAD_L - 3, H - PAD_B - 5)
}

export function VolumeProfilePanel() {
  const vp = useTerminal((s) => s.s1_state?.volume_profile)
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
    if (canvasRef.current) draw(canvasRef.current, vp?.value, box)
  }, [vp, box])

  const fresh = vp?.freshness
  const val = vp?.value
  const levels = Array.isArray(val?.levels) ? val!.levels : []
  const noData = fresh === 'ABSENT' || levels.length === 0
  const fmt = (n: number | null | undefined) => (typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : '·')

  return (
    <Panel code="VP" title="Volume Profile · VA/POC" block="s1_state.volume_profile" accent="sony"
      right={<span className="tabular-nums text-xxs text-term-faint">POC {fmt(val?.poc)} · {levels.length} niv</span>}>
      <div className={cn('flex h-full min-h-0 flex-col', fresh === 'STALE' && 'opacity-60')}>
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
        <p className="shrink-0 border-t border-term-border pt-0.5 text-xxs text-term-faint">
          <span className="text-router">▬ POC</span> ·{' '}
          <span className="text-[rgb(56,189,248)]">▮ VA {val ? Math.round((val.va_pct ?? 0.7) * 100) : 70}%</span> ·{' '}
          <span className="text-[rgb(167,139,250)]">┄ veille</span> ·{' '}
          <span className="text-[rgb(251,191,36)]">◄ LVN</span>
        </p>
      </div>
    </Panel>
  )
}
