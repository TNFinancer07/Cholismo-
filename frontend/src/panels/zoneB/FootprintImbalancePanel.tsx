/** Panneau FOOTPRINT + IMBALANCES (D-037) — lit UN champ : `s1_state.footprint` (CLAUDE §1).
 *  Rend en HTML5 Canvas les bougies footprint : colonnes = bougies (temps), lignes = niveaux de
 *  prix (axe partagé). Chaque cellule = `bid × ask` ; IMBALANCES diagonales en surbrillance
 *  (fond VERT = ASK/achat + ▲ / ROUGE = BID/vente + ▼ — couleur JAMAIS seule, §3, ALPHA gradué
 *  selon l'intensité du volume) ; POC de chaque bougie marqué en OR (au PREMIER PLAN) ; fine
 *  bougie OHLC en rappel de l'action des prix. /polish : cellules qui s'AJUSTENT à la taille du
 *  panneau (police adaptative sans chevauchement), tracé ALIGNÉ AU PIXEL (lignes nettes).
 *  LECTURE SEULE (§2.1). FAIL-CLOSED (§3) : périmé → FIGÉ ; vide → « PAS DE DONNÉES ». */
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { FootprintValue } from '@/types/schema'

const GREEN = '52, 211, 153', RED = '248, 113, 113', GOLD = '240, 180, 41'
const PRICE_W = 50, HEAD_H = 15
const MIN_CW = 40, MAX_CW = 132, MIN_RH = 12, MAX_RH = 26
const MAX_ROWS = 400, MAX_CANDLES = 60
const R = Math.round

// compact + robuste : non-fini → « · » ; gros volumes → k/M (cellule jamais débordée).
function fmt(v: number): string {
  if (!Number.isFinite(v)) return '·'
  const a = Math.abs(v)
  if (a >= 1e6) return R(v / 1e5) / 10 + 'M'
  if (a >= 1000) return R(v / 100) / 10 + 'k'
  return String(R(v))
}

function draw(canvas: HTMLCanvasElement, fp: FootprintValue | null | undefined, box: { w: number; h: number }) {
  const dpr = window.devicePixelRatio || 1
  const cands = (fp?.candles ?? []).slice(-MAX_CANDLES)
  const tick = fp?.tick ?? 0.25
  let pmin = Infinity, pmax = -Infinity
  for (const c of cands) for (const l of c.levels) {
    if (Number.isFinite(l.price)) { if (l.price < pmin) pmin = l.price; if (l.price > pmax) pmax = l.price }
  }
  if (box.w < 2 || box.h < 2 || cands.length === 0 || !Number.isFinite(pmin)
      || !Number.isFinite(pmax) || pmax < pmin || !(tick > 0)) {
    canvas.width = 1; canvas.height = 1; return
  }
  // fenêtre de prix bornée (un prix aberrant lointain n'explose pas le canvas — /devil).
  const rows = Math.max(1, Math.min(R((pmax - pmin) / tick) + 1, MAX_ROWS))
  const pminD = pmax - (rows - 1) * tick
  // cellules AJUSTÉES au panneau, bornées (s'étirent si grand, défilent si dense).
  const CW = Math.max(MIN_CW, Math.min(MAX_CW, Math.floor((box.w - PRICE_W) / cands.length)))
  const RH = Math.max(MIN_RH, Math.min(MAX_RH, Math.floor((box.h - HEAD_H) / rows)))
  const W = PRICE_W + cands.length * CW, H = HEAD_H + rows * RH
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px'
  canvas.width = R(W * dpr); canvas.height = R(H * dpr)
  const ctx = canvas.getContext('2d'); if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, W, H)
  ctx.textBaseline = 'middle'

  const yOf = (price: number) => HEAD_H + R((pmax - price) / tick) * RH   // toujours entier

  // police ADAPTATIVE : mesure la cellule la plus large, choisit une taille qui tient en
  // largeur ET hauteur → séparateur/glyphe ne chevauchent jamais les chiffres.
  let maxV = 0
  for (const c of cands) for (const l of c.levels) {
    if (Number.isFinite(l.bid_vol) && l.bid_vol > maxV) maxV = l.bid_vol
    if (Number.isFinite(l.ask_vol) && l.ask_vol > maxV) maxV = l.ask_vol
  }
  ctx.font = '10px "JetBrains Mono", ui-monospace, monospace'
  const widest = ctx.measureText(`${fmt(maxV)}×${fmt(maxV)}▼`).width || 1
  const fontSize = Math.min(RH * 0.64, (10 * (CW - 7)) / widest, 14)
  const showText = fontSize >= 7 && RH >= 10 && CW >= 34
  ctx.font = `${Math.max(7, Math.floor(fontSize))}px "JetBrains Mono", ui-monospace, monospace`

  // gouttière prix (une étiquette sur deux si dense)
  ctx.fillStyle = '#67788f'; ctx.textAlign = 'right'
  const step = RH >= 12 ? 1 : 2
  for (let r = 0; r < rows; r += step) {
    if (showText) ctx.fillText((pmax - r * tick).toFixed(2), PRICE_W - 4, yOf(pmax - r * tick) + RH / 2)
  }

  cands.forEach((c, j) => {
    const x0 = PRICE_W + j * CW
    // intensité du volume dans cette bougie → alpha gradué (borné pour rester lisible)
    let sideMax = 0
    for (const l of c.levels) {
      if (Number.isFinite(l.bid_vol)) sideMax = Math.max(sideMax, l.bid_vol)
      if (Number.isFinite(l.ask_vol)) sideMax = Math.max(sideMax, l.ask_vol)
    }
    // fine bougie OHLC (bord gauche) — seulement si OHLC fini
    if (Number.isFinite(c.open) && Number.isFinite(c.high) && Number.isFinite(c.low) && Number.isFinite(c.close)) {
      const up = c.close >= c.open
      ctx.strokeStyle = up ? `rgba(${GREEN}, 0.5)` : `rgba(${RED}, 0.5)`
      ctx.fillStyle = up ? `rgba(${GREEN}, 0.35)` : `rgba(${RED}, 0.35)`
      const cx = R(x0 + 3) + 0.5
      ctx.beginPath(); ctx.moveTo(cx, yOf(c.high)); ctx.lineTo(cx, yOf(c.low)); ctx.stroke()
      const yo = yOf(c.open), yc = yOf(c.close)
      ctx.fillRect(R(x0 + 1), Math.min(yo, yc), 4, Math.max(2, Math.abs(yc - yo)))
    }

    const cellX = R(x0 + 7), cellW = R(CW - 8)
    for (const l of c.levels) {
      if (!Number.isFinite(l.price) || l.price < pminD) continue
      const y = yOf(l.price)
      // fond d'imbalance : alpha proportionnel au volume du côté imbalancé (0.12 → 0.44)
      if (l.imbalance === 'ASK' || l.imbalance === 'BID') {
        const vol = l.imbalance === 'ASK' ? l.ask_vol : l.bid_vol
        const intensity = sideMax > 0 && Number.isFinite(vol) ? Math.min(1, vol / sideMax) : 0
        const alpha = 0.12 + 0.32 * intensity
        ctx.fillStyle = `rgba(${l.imbalance === 'ASK' ? GREEN : RED}, ${alpha.toFixed(3)})`
        ctx.fillRect(cellX, R(y), cellW, R(RH))
      }
      // texte bid×ask ; côté imbalancé coloré + glyphe (couleur jamais seule §3)
      if (showText) {
        ctx.textAlign = 'center'
        ctx.fillStyle = l.imbalance === 'BID' ? `rgb(${RED})` : l.imbalance === 'ASK' ? `rgb(${GREEN})` : '#c9d4e3'
        const glyph = l.imbalance === 'ASK' ? '▲' : l.imbalance === 'BID' ? '▼' : ''
        ctx.fillText(`${fmt(l.bid_vol)}×${fmt(l.ask_vol)}${glyph}`, cellX + cellW / 2, R(y) + RH / 2)
      }
      // POC AU PREMIER PLAN : barre + contour OR, dessinés APRÈS le fond/texte de la cellule.
      if (c.poc !== null && l.price === c.poc) {
        ctx.fillStyle = `rgba(${GOLD}, 0.95)`; ctx.fillRect(cellX, R(y) + 1, 2, R(RH) - 2)
        ctx.strokeStyle = `rgba(${GOLD}, 0.95)`; ctx.lineWidth = 1
        ctx.strokeRect(cellX + 0.5, R(y) + 0.5, cellW - 1, R(RH) - 1)
      }
    }
    // entête : heure de la bougie
    if (showText) {
      ctx.fillStyle = '#67788f'; ctx.textAlign = 'center'
      ctx.fillText(new Date(c.start_ts * 1000).toLocaleTimeString('en-GB', { hour12: false }).slice(0, 5),
        R(x0 + CW / 2), R(HEAD_H / 2))
    }
  })
}

export function FootprintImbalancePanel() {
  const fp = useTerminal((s) => s.s1_state?.footprint)
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
    if (canvasRef.current) draw(canvasRef.current, fp?.value, box)
  }, [fp, box])

  const fresh = fp?.freshness
  const cands = fp?.value?.candles ?? []
  const noData = fresh === 'ABSENT' || cands.length === 0
  const ratio = fp?.value?.ratio ?? 3

  return (
    <Panel code="FP" title="Footprint · imbalances" block="s1_state.footprint" accent="sony"
      right={<span className="tabular-nums text-xxs text-term-faint">{cands.length} bougie{cands.length > 1 ? 's' : ''}</span>}>
      <div className={cn('flex h-full min-h-0 flex-col', fresh === 'STALE' && 'opacity-60')}>
        <div ref={wrapRef} className="relative min-h-0 flex-1 overflow-auto">
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
          bid×ask · <span className="text-risk-green">▲ ASK</span> ·{' '}
          <span className="text-risk-red">▼ BID</span> (≥ {ratio}× diagonal, alpha ∝ volume) ·{' '}
          <span className="text-router">▮ POC</span>
        </p>
      </div>
    </Panel>
  )
}
