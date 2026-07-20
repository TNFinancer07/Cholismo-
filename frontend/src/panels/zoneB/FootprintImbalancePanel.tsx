/** Panneau FOOTPRINT + IMBALANCES (D-037) — lit UN champ : `s1_state.footprint` (CLAUDE §1).
 *  Rend en HTML5 Canvas les bougies footprint : colonnes = bougies (temps), lignes = niveaux de
 *  prix (axe partagé). Chaque cellule = `bid × ask` ; les IMBALANCES diagonales sont mises en
 *  surbrillance (fond VERT = ASK/achat, ROUGE = BID/vente + glyphe ▲/▼ — couleur JAMAIS seule,
 *  §3) ; le POC de chaque bougie est marqué en OR ; une fine bougie OHLC rappelle l'action des
 *  prix. Grille dimensionnée au contenu → défile (cellules toujours lisibles). LECTURE SEULE :
 *  aucun affordance de passage d'ordre (§2.1). FAIL-CLOSED (§3) : périmé → FIGÉ ; vide → « PAS
 *  DE DONNÉES ». */
import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { FootprintValue } from '@/types/schema'

const GREEN = '52, 211, 153'    // ASK imbalance (achat)
const RED = '248, 113, 113'     // BID imbalance (vente)
const GOLD = '240, 180, 41'     // POC (router)
const PRICE_W = 52, CW = 62, RH = 14, HEAD_H = 15   // gouttière prix, largeur bougie, hauteur ligne, entête
const MAX_ROWS = 400, MAX_CANDLES = 60              // bornes de rendu (canvas fini, /devil)

// compact + robuste : non-fini → « · » ; gros volumes → k/M (cellule jamais débordée).
function fmt(v: number): string {
  if (!Number.isFinite(v)) return '·'
  const a = Math.abs(v)
  if (a >= 1e6) return Math.round(v / 1e5) / 10 + 'M'
  if (a >= 1000) return Math.round(v / 100) / 10 + 'k'
  return String(Math.round(v))
}

function draw(canvas: HTMLCanvasElement, fp: FootprintValue | null | undefined) {
  const cands = (fp?.candles ?? []).slice(-MAX_CANDLES)
  const tick = fp?.tick ?? 0.25
  // étendue de prix partagée (grille de tick) — seuls les prix FINIS comptent.
  let pmin = Infinity, pmax = -Infinity
  for (const c of cands) for (const l of c.levels) {
    if (Number.isFinite(l.price)) { if (l.price < pmin) pmin = l.price; if (l.price > pmax) pmax = l.price }
  }
  const dpr = window.devicePixelRatio || 1
  // garde : `!(tick > 0)` capture aussi NaN ; range non-finie / vide → canvas neutre.
  if (cands.length === 0 || !Number.isFinite(pmin) || !Number.isFinite(pmax) || pmax < pmin || !(tick > 0)) {
    canvas.width = 1; canvas.height = 1; return
  }
  // fenêtre de prix BORNÉE à MAX_ROWS (un prix aberrant lointain ne fait pas exploser le canvas).
  const rows = Math.max(1, Math.min(Math.round((pmax - pmin) / tick) + 1, MAX_ROWS))
  const pminD = pmax - (rows - 1) * tick
  const W = PRICE_W + cands.length * CW
  const H = HEAD_H + rows * RH
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px'
  canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr)
  const ctx = canvas.getContext('2d'); if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, W, H)
  ctx.textBaseline = 'middle'
  ctx.font = '9px "JetBrains Mono", ui-monospace, monospace'
  const yOf = (price: number) => HEAD_H + Math.round((pmax - price) / tick) * RH

  // gouttière prix (une étiquette sur deux si dense)
  ctx.fillStyle = '#67788f'
  const step = RH >= 12 ? 1 : 2
  for (let r = 0; r < rows; r += step) {
    const price = pmax - r * tick
    ctx.textAlign = 'right'
    ctx.fillText(price.toFixed(2), PRICE_W - 4, HEAD_H + r * RH + RH / 2)
  }

  cands.forEach((c, j) => {
    const x0 = PRICE_W + j * CW
    // fine bougie OHLC (rappel de l'action des prix) — seulement si OHLC fini (§3 défensif).
    if (Number.isFinite(c.open) && Number.isFinite(c.high) && Number.isFinite(c.low) && Number.isFinite(c.close)) {
      const up = c.close >= c.open
      ctx.strokeStyle = up ? `rgba(${GREEN}, 0.5)` : `rgba(${RED}, 0.5)`
      ctx.fillStyle = up ? `rgba(${GREEN}, 0.35)` : `rgba(${RED}, 0.35)`
      const cx = x0 + 3
      ctx.beginPath(); ctx.moveTo(cx, yOf(c.high)); ctx.lineTo(cx, yOf(c.low)); ctx.stroke()
      const yo = yOf(c.open), yc = yOf(c.close)
      ctx.fillRect(x0 + 1, Math.min(yo, yc), 4, Math.max(2, Math.abs(yc - yo)))
    }

    for (const l of c.levels) {
      if (!Number.isFinite(l.price) || l.price < pminD) continue   // hors-grille / hors-fenêtre → ignoré
      const y = yOf(l.price)
      // fond de surbrillance d'imbalance
      if (l.imbalance === 'ASK') { ctx.fillStyle = `rgba(${GREEN}, 0.22)`; ctx.fillRect(x0 + 7, y, CW - 8, RH) }
      else if (l.imbalance === 'BID') { ctx.fillStyle = `rgba(${RED}, 0.22)`; ctx.fillRect(x0 + 7, y, CW - 8, RH) }
      // marqueur POC (or) : liseré gauche
      if (c.poc !== null && l.price === c.poc) {
        ctx.fillStyle = `rgba(${GOLD}, 0.9)`; ctx.fillRect(x0 + 7, y + 1, 2, RH - 2)
      }
      // texte bid×ask ; côté imbalancé coloré + glyphe (couleur jamais seule §3)
      const cyc = y + RH / 2
      ctx.textAlign = 'center'
      ctx.fillStyle = l.imbalance === 'BID' ? `rgb(${RED})` : l.imbalance === 'ASK' ? `rgb(${GREEN})` : '#c9d4e3'
      const glyph = l.imbalance === 'ASK' ? '▲' : l.imbalance === 'BID' ? '▼' : ''
      ctx.fillText(`${fmt(l.bid_vol)}×${fmt(l.ask_vol)}${glyph}`, x0 + 7 + (CW - 8) / 2, cyc)
    }
    // entête : heure de la bougie
    ctx.fillStyle = '#67788f'; ctx.textAlign = 'center'
    ctx.fillText(new Date(c.start_ts * 1000).toLocaleTimeString('en-GB', { hour12: false }).slice(0, 5),
      x0 + CW / 2, HEAD_H / 2)
  })
}

export function FootprintImbalancePanel() {
  const fp = useTerminal((s) => s.s1_state?.footprint)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (canvasRef.current) draw(canvasRef.current, fp?.value)
  }, [fp])

  const fresh = fp?.freshness
  const cands = fp?.value?.candles ?? []
  const noData = fresh === 'ABSENT' || cands.length === 0
  const ratio = fp?.value?.ratio ?? 3

  return (
    <Panel code="FP" title="Footprint · imbalances" block="s1_state.footprint" accent="sony"
      right={<span className="tabular-nums text-xxs text-term-faint">{cands.length} bougie{cands.length > 1 ? 's' : ''}</span>}>
      <div className={cn('relative flex min-h-0 flex-col', fresh === 'STALE' && 'opacity-60')}>
        <div className="min-h-0 flex-1 overflow-auto">
          <canvas ref={canvasRef} className="block" />
        </div>
        {noData && (
          <div className="absolute inset-0 grid place-items-center">
            <span className="absent-pulse font-mono text-xs font-bold text-absent">PAS DE DONNÉES</span>
          </div>
        )}
        {fresh === 'STALE' && (
          <span className="absolute right-1 top-1 border border-stale/50 px-1 text-xxs font-bold text-stale">FIGÉ</span>
        )}
        <p className="shrink-0 border-t border-term-border pt-0.5 text-xxs text-term-faint">
          bid×ask · <span className="text-risk-green">▲ imbalance ASK</span> ·{' '}
          <span className="text-risk-red">▼ imbalance BID</span> (ratio ≥ {ratio}× diagonal) ·{' '}
          <span className="text-router">▮ POC</span>
        </p>
      </div>
    </Panel>
  )
}
