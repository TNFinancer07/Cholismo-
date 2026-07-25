/** Panneau FOOTPRINT · IMBALANCES · DELTA · MURS L2 (D-037 + D-042) — lit UN champ :
 *  `s1_state.footprint` (CLAUDE §1). Rend en HTML5 Canvas : colonnes = bougies, lignes = niveaux de
 *  prix (axe partagé), cellule = `bid × ask`.
 *
 *  - IMBALANCES diagonales en surbrillance (fond VERT = ASK/achat + ▲ / ROUGE = BID/vente + ▼,
 *    ALPHA gradué selon l'intensité du volume) ; POC en OR au PREMIER PLAN ; fine bougie OHLC.
 *  - DELTA (D-042) : agresseur net, en en-tête de chaque colonne et dans l'en-tête du panneau pour
 *    la bougie en formation. Le SIGNE et le GLYPHE portent le sens — la couleur n'est jamais seule
 *    (§3) ; un delta nul ne reçoit AUCUN glyphe directionnel (pas de sens inventé).
 *  - MURS L2 (D-042) : liquidité AU REPOS du carnet, bande dédiée à droite, bougie EN FORMATION
 *    uniquement (le carnet est un instantané courant : l'étendre au passé serait faux). Le CÔTÉ est
 *    encodé par la POSITION (gauche = bid/support, droite = ask/résistance), pas par la seule teinte.
 *    La bande est TOUJOURS réservée : si sa largeur dépendait de `book_state`, un carnet qui clignote
 *    (LIVE↔ABSENT au gré de la fraîcheur) ferait sauter toute la grille latéralement.
 *
 *  Cellules AJUSTÉES à la taille du panneau (police adaptative sans chevauchement), tracé ALIGNÉ AU
 *  PIXEL. LECTURE SEULE (§2.1). FAIL-CLOSED (§3) : périmé → FIGÉ ; vide → « PAS DE DONNÉES » ;
 *  carnet indisponible → colonne L2 marquée d'un tiret neutre + légende explicite, jamais un blanc
 *  qui se lirait « aucun mur ». */
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { FootprintCandle, FootprintValue } from '@/types/schema'

const GREEN = '52, 211, 153', RED = '248, 113, 113', GOLD = '240, 180, 41'
const SKY = '56, 189, 248'      // liquidité AU REPOS (L2) — distincte de l'agresseur (vert/rouge)
const PRICE_W = 50, HEAD_H = 27  // 2 lignes d'en-tête : heure + delta de la bougie (D-042)
const L2_W = 34                  // bande des murs L2, à droite de la bougie en formation (D-042)
const MIN_CW = 40, MAX_CW = 132, MIN_RH = 12, MAX_RH = 26
const MAX_ROWS = 400, MAX_CANDLES = 60
const R = Math.round

/** Magnitude compacte (k/M) — garde la cellule à largeur bornée quel que soit le volume. */
function compact(a: number): string {
  if (a >= 1e6) return R(a / 1e5) / 10 + 'M'
  if (a >= 1000) return R(a / 100) / 10 + 'k'
  return String(R(a))
}

/** Volume (toujours ≥ 0) — non-fini → « · », jamais une valeur inventée (§3). */
function fmt(v: number): string {
  return Number.isFinite(v) ? compact(Math.abs(v)) : '·'
}

/** Delta signé — le SIGNE porte le sens, indépendamment de la couleur (§3). Zéro reste « 0 »,
 *  sans signe : une absence de déséquilibre n'est ni une hausse ni une baisse. */
function fmtSignedCompact(v: number): string {
  if (!Number.isFinite(v)) return '·'
  return (v > 0 ? '+' : v < 0 ? '−' : '') + compact(Math.abs(v))
}

/** Murs L2 exploitables de la bougie en formation, ou `null`. Exige `book_state === 'LIVE'` ET au
 *  moins une liquidité finie > 0 : sinon aucune barre n'est tracée plutôt que d'en inventer (§3) —
 *  la colonne reste en place et son vide est marqué explicitement. */
function l2Walls(c: FootprintCandle | undefined): { max: number } | null {
  if (!c || c.book_state !== 'LIVE') return null
  let max = 0
  for (const l of c.levels) {
    if (Number.isFinite(l.bid_liq)) max = Math.max(max, l.bid_liq as number)
    if (Number.isFinite(l.ask_liq)) max = Math.max(max, l.ask_liq as number)
  }
  return max > 0 ? { max } : null
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
  // fenêtre de prix BORNÉE : un prix aberrant lointain n'explose jamais la hauteur du canvas.
  const rows = Math.max(1, Math.min(R((pmax - pmin) / tick) + 1, MAX_ROWS))
  const pminD = pmax - (rows - 1) * tick
  // cellules AJUSTÉES au panneau, bornées (s'étirent si grand, défilent si dense).
  const walls = l2Walls(cands[cands.length - 1])          // murs L2 : bougie en formation seule
  // La bande L2 est TOUJOURS réservée : sa largeur ne doit pas dépendre de `book_state`, sinon un
  // carnet qui clignote (LIVE↔ABSENT au gré de la fraîcheur) ferait sauter toute la grille
  // latéralement à chaque bascule. Colonne stable ; c'est son CONTENU qui varie.
  const CW = Math.max(MIN_CW, Math.min(MAX_CW,
    Math.floor((box.w - PRICE_W - L2_W) / cands.length)))
  const RH = Math.max(MIN_RH, Math.min(MAX_RH, Math.floor((box.h - HEAD_H) / rows)))
  const W = PRICE_W + cands.length * CW + L2_W, H = HEAD_H + rows * RH
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
    // entête : heure (ligne 1) + DELTA de la bougie (ligne 2, D-042). Le signe et le glyphe
    // portent le sens — la couleur n'est jamais seule (§3).
    if (showText) {
      ctx.textAlign = 'center'
      const xc = R(x0 + CW / 2)
      ctx.fillStyle = '#67788f'
      ctx.fillText(new Date(c.start_ts * 1000).toLocaleTimeString('en-GB', { hour12: false }).slice(0, 5),
        xc, R(HEAD_H / 3))
      const d = c.delta
      const up = Number.isFinite(d) && d > 0, flat = !Number.isFinite(d) || d === 0
      ctx.fillStyle = flat ? '#67788f' : up ? `rgb(${GREEN})` : `rgb(${RED})`
      ctx.fillText(`${flat ? '' : up ? '▲' : '▼'}${fmtSignedCompact(d)}`, xc, R(HEAD_H * 0.74))
    }
  })

  drawL2Strip(ctx, { x: PRICE_W + cands.length * CW, H, RH, pminD, showText, yOf },
    cands[cands.length - 1], walls)
}

/** Bande des murs L2, à droite de la grille — bougie EN FORMATION uniquement (voir en-tête de
 *  fichier). Toujours dessinée pour garder la géométrie stable : avec un carnet vivant elle porte
 *  les barres de liquidité (gauche = bid/support, droite = ask/résistance) ; sans carnet elle porte
 *  un tiret neutre par niveau, qui DIT l'absence au lieu de la laisser passer pour « aucun mur ». */
function drawL2Strip(
  ctx: CanvasRenderingContext2D,
  geo: { x: number; H: number; RH: number; pminD: number; showText: boolean; yOf: (p: number) => number },
  forming: FootprintCandle | undefined,
  walls: { max: number } | null,
): void {
  if (!forming) return
  const { x, H, RH, pminD, showText, yOf } = geo
  const half = (L2_W - 3) / 2
  const mid = R(x + L2_W / 2)
  const visible = forming.levels.filter((l) => Number.isFinite(l.price) && l.price >= pminD)

  ctx.fillStyle = '#67788f'; ctx.textAlign = 'center'
  if (showText) ctx.fillText('L2', mid, R(HEAD_H / 3))
  ctx.strokeStyle = 'rgba(103, 120, 143, 0.5)'; ctx.lineWidth = 1   // frontière bid | ask
  ctx.beginPath(); ctx.moveTo(mid + 0.5, HEAD_H); ctx.lineTo(mid + 0.5, H); ctx.stroke()

  if (!walls) {
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.35)'
    for (const l of visible) {
      const y = R(yOf(l.price)) + R(RH / 2) + 0.5
      ctx.beginPath(); ctx.moveTo(mid - 4, y); ctx.lineTo(mid + 5, y); ctx.stroke()
    }
    return
  }
  for (const l of visible) {
    const y = R(yOf(l.price)) + 1, h = Math.max(1, R(RH) - 2)
    const bid = Number.isFinite(l.bid_liq) ? (l.bid_liq as number) : 0
    const ask = Number.isFinite(l.ask_liq) ? (l.ask_liq as number) : 0
    if (bid > 0) {                                     // support : barre vers la GAUCHE du centre
      const w = Math.max(1, R((bid / walls.max) * half))
      ctx.fillStyle = `rgba(${SKY}, 0.75)`; ctx.fillRect(mid - w, y, w, h)
    }
    if (ask > 0) {                                     // résistance : barre vers la DROITE
      const w = Math.max(1, R((ask / walls.max) * half))
      ctx.fillStyle = `rgba(${SKY}, 0.45)`; ctx.fillRect(mid + 1, y, w, h)
    }
  }
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
  const forming = cands[cands.length - 1]
  const delta = forming?.delta
  const hasDelta = typeof delta === 'number' && Number.isFinite(delta)
  // Carnet L2 : LIVE seulement si le backend l'affirme. Sinon l'absence est DITE — une bande
  // vide se lirait « aucun mur » alors qu'on n'en sait rien (§3).
  const bookLive = forming?.book_state === 'LIVE'

  return (
    <Panel code="FP" title="Footprint · imbalances" block="s1_state.footprint" accent="sony"
      right={
        <span className="flex items-center gap-2 tabular-nums text-xxs">
          {hasDelta && (
            <span className={cn('font-bold', delta > 0 ? 'text-risk-green' : delta < 0 ? 'text-risk-red' : 'text-term-dim')}
              title="Delta agresseur net de la bougie en formation (Σ des deltas de niveau)">
              {delta > 0 ? '▲' : delta < 0 ? '▼' : ''} Δ {fmtSignedCompact(delta)}
            </span>
          )}
          <span className="text-term-faint">{cands.length} bougie{cands.length > 1 ? 's' : ''}</span>
        </span>
      }>
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
          <span className="text-router">▮ POC</span> · Δ delta ·{' '}
          {bookLive
            ? <span className="text-[rgb(56,189,248)]">▮ L2 murs au repos (bougie en formation)</span>
            : <span className="text-stale">L2 carnet absent — murs non affichés</span>}
        </p>
      </div>
    </Panel>
  )
}
