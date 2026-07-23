/** Panneau VP — Volume Profile dynamique (D-041) — lit UN champ : `s1_state.volume_profile`
 *  (CLAUDE §1). Histogramme HORIZONTAL en HTML5 Canvas : axe Y = PRIX (haut = haut), axe X =
 *  VOLUME (barres vers la droite). Hiérarchie visuelle STRICTE : POC (barre + ligne OR) > Value
 *  Area (barres + bande SKY, bornes VAH/VAL tracées) > hors-VA (slate atténué) ; niveaux de la
 *  VEILLE (prev POC/VAH/VAL, tiretés VIOLETS libellés) ; Low Volume Nodes (◄ AMBRE). Chaque repère
 *  = couleur + glyphe/position + libellé (jamais la couleur seule §3). INTERACTIF : survol → réticule
 *  horizontal + infobulle (prix, volume, part % de la session, split acheteur/vendeur si la source
 *  le fournit). LECTURE SEULE (§2.1). FAIL-CLOSED (§3) : périmé → FIGÉ ; vide → « PAS DE DONNÉES ». */
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { VolumeProfileValue } from '@/types/schema'

const GOLD = '240, 180, 41', SKY = '56, 189, 248', VIOLET = '167, 139, 250', AMBER = '251, 191, 36'
const BUY = '45, 212, 191', SELL = '148, 163, 184'    // split tooltip : teal acheteur / slate vendeur (labellisés)
const PAD_L = 44, PAD_R = 8, PAD_T = 6, PAD_B = 6
const R = Math.round

// volume compact (k/M) — non-fini → « · » (jamais un « NaN » affiché, §3)
function fmt(v: number | null | undefined): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '·'
  const a = Math.abs(v)
  if (a >= 1e6) return R(a / 1e5) / 10 + 'M'
  if (a >= 1000) return R(a / 100) / 10 + 'k'
  return String(R(a))
}

function draw(canvas: HTMLCanvasElement, vp: VolumeProfileValue | null | undefined,
             box: { w: number; h: number }, hoverY: number | null) {
  const dpr = window.devicePixelRatio || 1
  const W = box.w, H = box.h
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px'
  canvas.width = R(W * dpr); canvas.height = R(H * dpr)          // buffer entier × DPR → aucun demi-pixel
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
  if (!(maxVol > 0)) return
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B
  // /devil : niveau unique (pmax==pmin, début de session) → barre centrée, jamais un canvas vide
  const flat = !(pmax > pmin)
  const yOf = (price: number) => flat ? PAD_T + plotH / 2 : PAD_T + ((pmax - price) / (pmax - pmin)) * plotH
  const rowH = flat ? Math.min(plotH, 22) : Math.max(1, plotH / levels.length)
  const barW = (v: number) => Math.max(0, (v / maxVol) * plotW)
  const tick = vp?.tick && vp.tick > 0 ? vp.tick : 0.25
  const total = Number.isFinite(vp?.total_volume) && vp!.total_volume > 0 ? vp!.total_volume : 0
  const inVA = (p: number) => Number.isFinite(vp?.vah) && Number.isFinite(vp?.val) && p <= vp!.vah! && p >= vp!.val!
  const isPoc = (p: number) => Number.isFinite(vp?.poc) && Math.abs(p - vp!.poc!) < tick / 2

  // bande Value Area (VAL → VAH) — repère neutre sky (position + bornes tracées + libellé aussi §3)
  if (Number.isFinite(vp?.vah) && Number.isFinite(vp?.val)) {
    const y0 = R(yOf(vp!.vah!) - rowH / 2), y1 = R(yOf(vp!.val!) + rowH / 2)
    ctx.fillStyle = `rgba(${SKY}, 0.11)`; ctx.fillRect(PAD_L, y0, plotW, Math.max(1, y1 - y0))
    // bornes VAH/VAL nettes (traits sky fins alignés au pixel) → la VA se lit d'un coup d'œil
    ctx.strokeStyle = `rgba(${SKY}, 0.5)`; ctx.lineWidth = 1
    for (const yy of [y0, y1]) { ctx.beginPath(); ctx.moveTo(PAD_L, yy + 0.5); ctx.lineTo(W - PAD_R, yy + 0.5); ctx.stroke() }
  }

  // barres de volume — hiérarchie POC(or) > VA(sky) > hors-VA(slate atténué)
  for (const l of levels) {
    const y = R(yOf(l.price) - rowH / 2), h = Math.max(1, R(rowH) - (rowH > 3 ? 1 : 0))
    ctx.fillStyle = isPoc(l.price) ? `rgba(${GOLD}, 0.92)`
      : inVA(l.price) ? `rgba(${SKY}, 0.62)` : 'rgba(103, 120, 143, 0.5)'
    ctx.fillRect(PAD_L, y, R(barW(l.volume)), h)
  }

  // lignes de repère horizontales (POC / veille) — bornées à la plage, pixel-net
  const hline = (price: number, color: string, dash: number[], width: number, label: string) => {
    if (!Number.isFinite(price)) return
    const yc = Math.max(pmin, Math.min(pmax, price))       // borné à la plage visible
    const y = R(yOf(yc)) + 0.5
    ctx.strokeStyle = `rgb(${color})`; ctx.lineWidth = width; ctx.setLineDash(dash)
    ctx.beginPath(); ctx.moveTo(PAD_L, y); ctx.lineTo(W - PAD_R, y); ctx.stroke(); ctx.setLineDash([])
    ctx.font = '8px "JetBrains Mono", ui-monospace, monospace'; ctx.fillStyle = `rgb(${color})`
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
    ctx.fillText(label, W - PAD_R - 1, y - 4)
  }
  // veille (violet tireté) — projection des niveaux de la session précédente
  const prev = vp?.previous
  if (prev) {
    hline(prev.val as number, VIOLET, [2, 2], 1, 'yVAL')
    hline(prev.vah as number, VIOLET, [2, 2], 1, 'yVAH')
    hline(prev.poc as number, VIOLET, [4, 2], 1.25, 'yPOC')
  }
  hline(vp?.poc as number, GOLD, [], 1.75, 'POC')          // POC = trait or plein, plus épais (au 1er plan)

  // LVN (creux) — marqueur ◄ ambre à gauche
  ctx.font = '8px "JetBrains Mono", ui-monospace, monospace'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
  for (const p of (Array.isArray(vp?.lvn) ? vp!.lvn : [])) {
    if (!Number.isFinite(p) || p < pmin || p > pmax) continue
    ctx.fillStyle = `rgb(${AMBER})`; ctx.fillText('◄', PAD_L + 1, R(yOf(p)))
  }

  // échelle prix (gouttière gauche) : haut / bas
  ctx.fillStyle = '#67788f'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
  ctx.font = '8px "JetBrains Mono", ui-monospace, monospace'
  ctx.fillText(pmax.toFixed(2), PAD_L - 3, PAD_T + 5)
  ctx.fillText(pmin.toFixed(2), PAD_L - 3, H - PAD_B - 5)

  // ---- survol : réticule horizontal + infobulle (prix, volume, part %, acheteur/vendeur) ----
  if (hoverY == null || hoverY < PAD_T - 4 || hoverY > H - PAD_B + 4) return
  let bi = -1, bestDy = Infinity                            // niveau le plus proche du curseur en Y
  for (let i = 0; i < levels.length; i++) {
    const dy = Math.abs(yOf(levels[i].price) - hoverY)
    if (dy < bestDy) { bestDy = dy; bi = i }
  }
  const l = bi >= 0 ? levels[bi] : null
  if (!l) return
  const yc = R(yOf(l.price)) + 0.5
  // réticule + surbrillance de la barre survolée (contour clair) — alignés au pixel (net à 100 %)
  ctx.strokeStyle = 'rgba(201, 212, 227, 0.35)'; ctx.lineWidth = 1
  ctx.beginPath(); ctx.moveTo(PAD_L, yc); ctx.lineTo(W - PAD_R, yc); ctx.stroke()
  const yb = R(yOf(l.price) - rowH / 2), hb = Math.max(1, R(rowH) - (rowH > 3 ? 1 : 0))
  ctx.strokeStyle = 'rgba(201, 212, 227, 0.85)'; ctx.lineWidth = 1
  ctx.strokeRect(PAD_L + 0.5, yb + 0.5, Math.max(1, R(barW(l.volume)) - 1), Math.max(1, hb - 1))

  // infobulle — libellés + valeurs sur bornes entières (aucun flou), part % de la session
  const part = total > 0 ? (l.volume / total) * 100 : null
  const tag = isPoc(l.price) ? ['POC', GOLD] as const
    : inVA(l.price) ? ['VALUE AREA', SKY] as const
      : (Array.isArray(vp?.lvn) && vp!.lvn.some((x) => Number.isFinite(x) && Math.abs(x - l.price) < tick / 2))
        ? ['LVN · creux', AMBER] as const : null
  const rows: [string, string, string][] = [
    ['prix', l.price.toFixed(2), '201, 212, 227'],
    ['vol', fmt(l.volume), '201, 212, 227'],
    ['part', part == null ? '·' : part.toFixed(1) + '%', '201, 212, 227'],
  ]
  if (Number.isFinite(l.buy) && Number.isFinite(l.sell)) {    // split seulement si source-backed (§3)
    const bp = l.volume > 0 ? R((l.buy! / l.volume) * 100) : 0
    rows.push(['ach', fmt(l.buy) + ' ' + bp + '%', BUY])
    rows.push(['vend', fmt(l.sell), SELL])
  }
  // COMPACT (9px, interligne 11) → le bloc tient dans un panneau court : ach/vend jamais rognés
  ctx.font = '9px "JetBrains Mono", ui-monospace, monospace'
  const LH = 11, bw = 112, bh = rows.length * LH + (tag ? LH + 1 : 0) + 5
  const bx = R(Math.min(W - bw - 2, PAD_L + Math.max(barW(l.volume) + 8, 8)))   // près de la barre, jamais hors-champ
  const by = R(Math.max(2, Math.min(H - bh - 2, yc - bh / 2)))                  // borné dans le canvas (aucun rognage)
  ctx.fillStyle = 'rgba(11, 15, 20, 0.94)'; ctx.fillRect(bx, by, bw, bh)
  ctx.strokeStyle = 'rgba(103, 120, 143, 0.6)'; ctx.strokeRect(bx + 0.5, by + 0.5, bw, bh)
  ctx.textBaseline = 'middle'
  let ry = by + 7
  if (tag) {
    ctx.textAlign = 'left'; ctx.fillStyle = `rgb(${tag[1]})`
    ctx.fillText('▬ ' + tag[0], bx + 6, ry); ry += LH + 1
  }
  rows.forEach(([label, v, color]) => {
    ctx.textAlign = 'left'; ctx.fillStyle = `rgb(${color})`; ctx.fillText(label, bx + 6, ry)
    ctx.textAlign = 'right'; ctx.fillStyle = '#c9d4e3'; ctx.fillText(v, bx + bw - 6, ry)
    ry += LH
  })
}

export function VolumeProfilePanel() {
  const vp = useTerminal((s) => s.s1_state?.volume_profile)
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const [hoverY, setHoverY] = useState<number | null>(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el); setBox({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    if (canvasRef.current) draw(canvasRef.current, vp?.value, box, hoverY)
  }, [vp, box, hoverY])

  const fresh = vp?.freshness
  const val = vp?.value
  const levels = Array.isArray(val?.levels) ? val!.levels : []
  const noData = fresh === 'ABSENT' || levels.length === 0
  const fmtp = (n: number | null | undefined) => (typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : '·')

  return (
    <Panel code="VP" title="Volume Profile · VA/POC" block="s1_state.volume_profile" accent="sony"
      right={<span className="tabular-nums text-xxs text-term-faint">POC {fmtp(val?.poc)} · {levels.length} niv</span>}>
      <div className={cn('flex h-full min-h-0 flex-col', fresh === 'STALE' && 'opacity-60')}>
        <div ref={wrapRef} className="relative min-h-0 flex-1">
          <canvas ref={canvasRef} className="block"
            onMouseMove={(e) => setHoverY(e.clientY - e.currentTarget.getBoundingClientRect().top)}
            onMouseLeave={() => setHoverY(null)} />
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
          <span className="text-[rgb(251,191,36)]">◄ LVN</span> · survol : détail
        </p>
      </div>
    </Panel>
  )
}
