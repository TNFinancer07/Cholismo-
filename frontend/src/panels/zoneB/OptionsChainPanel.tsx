/** Panneau OMON — Moniteur de chaîne d'options (D-039) — lit UN champ : `vol_surface.options_chain`
 *  (CLAUDE §1). Divisé en deux : (haut) SKEW/SMILE en HTML5 Canvas — IV Call vs Put par strike sur
 *  l'échéance sélectionnée, marqueur ATM ; (bas) GRILLE haute densité — par échéance, Call/Put avec
 *  IV + grecque sélectionnable (Δ/Γ/Vanna/Charm), ligne ATM surlignée, moneyness ITM/ATM/OTM (jamais
 *  la couleur seule §3 : position + libellé). INTERACTIF : onglets d'échéance + sélecteur de grecque.
 *  LECTURE SEULE (§2.1). FAIL-CLOSED (§3) : périmé → FIGÉ ; vide → « PAS DE DONNÉES ». */
import { useEffect, useMemo, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { OptionExpiry, OptionsChainValue } from '@/types/schema'

const CALL = '56, 189, 248'   // sky — Call IV (ni risque, ni opérateur)
const PUT = '244, 114, 182'   // rose — Put IV
const GOLD = '240, 180, 41'   // ATM / repère
const R = Math.round
type Greek = 'delta' | 'gamma' | 'theta' | 'vega' | 'vanna' | 'charm'
const GREEKS: Greek[] = ['delta', 'gamma', 'theta', 'vega', 'vanna', 'charm']
// Le moteur fixe ses conventions (theta par AN, vega pour σ+1.0) ; la table affiche les unités
// que lit un opérateur — theta PAR JOUR, vega PAR POINT de vol — et le libellé le dit (D-044).
const G_SCALE: Record<Greek, number> = { delta: 1, gamma: 1, theta: 1 / 365, vega: 1 / 100, vanna: 1, charm: 1 }
const scaled = (v: number | null | undefined, g: Greek): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v * G_SCALE[g] : null

function num(v: number | null | undefined, d = 2): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '·'
}
function pct(v: number | null | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? (v * 100).toFixed(1) : '·'
}

// SKEW : IV Call & Put vs strike (échéance courante). Marqueur ATM. Tracé aligné au pixel.
function drawSkew(canvas: HTMLCanvasElement, exp: OptionExpiry | undefined, box: { w: number; h: number }) {
  const dpr = window.devicePixelRatio || 1
  const W = box.w, H = box.h
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px'
  canvas.width = R(W * dpr); canvas.height = R(H * dpr)
  const ctx = canvas.getContext('2d'); if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H)
  const rows = Array.isArray(exp?.rows) ? exp!.rows : []   // /devil : rows non-tableau → jamais .map crash
  if (W < 4 || H < 4 || rows.length === 0) return

  const strikes = rows.map((r) => r.strike).filter(Number.isFinite)
  const ivs: number[] = []
  for (const r of rows) for (const v of [r.call?.iv, r.put?.iv]) if (typeof v === 'number' && Number.isFinite(v)) ivs.push(v)
  if (strikes.length < 2 || ivs.length === 0) return
  const smin = Math.min(...strikes), smax = Math.max(...strikes)
  let imin = Math.min(...ivs), imax = Math.max(...ivs)
  if (imax - imin < 1e-6) { imax += 0.01; imin -= 0.01 }
  const PL = 34, PR = 6, PT = 6, PB = 12
  const xOf = (s: number) => PL + (smax === smin ? (W - PL - PR) / 2 : ((s - smin) / (smax - smin)) * (W - PL - PR))
  const yOf = (iv: number) => PT + ((imax - iv) / (imax - imin)) * (H - PT - PB)

  // marqueur ATM (vertical or) — repère de moneyness (position, pas couleur seule) + strike libellé
  if (exp?.atm_strike != null && Number.isFinite(exp.atm_strike)) {
    const x = R(xOf(exp.atm_strike)) + 0.5
    ctx.strokeStyle = `rgba(${GOLD}, 0.6)`; ctx.lineWidth = 1; ctx.setLineDash([3, 3])
    ctx.beginPath(); ctx.moveTo(x, PT); ctx.lineTo(x, H - PB); ctx.stroke(); ctx.setLineDash([])
    ctx.font = '8px "JetBrains Mono", ui-monospace, monospace'; ctx.fillStyle = `rgb(${GOLD})`
    ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic'
    ctx.fillText(String(R(exp.atm_strike)), Math.max(PL + 12, Math.min(W - PR - 12, R(x))), H - 3)
  }
  // axes IV (min/max) + libellés — alignés au pixel
  ctx.font = '8px "JetBrains Mono", ui-monospace, monospace'; ctx.fillStyle = '#67788f'
  ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
  ctx.fillText((imax * 100).toFixed(0), PL - 3, R(yOf(imax)) + 4)
  ctx.fillText((imin * 100).toFixed(0), PL - 3, R(yOf(imin)) - 4)

  const line = (key: 'call' | 'put', color: string) => {
    ctx.strokeStyle = `rgb(${color})`; ctx.lineWidth = 1.5; ctx.beginPath()
    let started = false
    for (const r of rows) {
      const iv = r[key]?.iv
      if (!Number.isFinite(r.strike) || typeof iv !== 'number' || !Number.isFinite(iv)) { started = false; continue }
      const x = xOf(r.strike), y = yOf(iv)
      if (!started) { ctx.moveTo(x, y); started = true } else ctx.lineTo(x, y)
    }
    ctx.stroke()
  }
  line('put', PUT); line('call', CALL)
}

export function OptionsChainPanel() {
  const oc = useTerminal((s) => s.vol_surface?.options_chain)
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const [expIdx, setExpIdx] = useState(0)
  const [greek, setGreek] = useState<Greek>('delta')

  const val: OptionsChainValue | null | undefined = oc?.value
  const exps = useMemo(() => (Array.isArray(val?.expirations) ? val!.expirations : []), [val])
  const idx = Math.min(expIdx, Math.max(0, exps.length - 1))
  const exp = exps[idx]

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el); setBox({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    if (canvasRef.current) drawSkew(canvasRef.current, exp, box)
  }, [exp, box])

  const fresh = oc?.freshness
  const noData = fresh === 'ABSENT' || exps.length === 0
  const gLabel: Record<Greek, string> = { delta: 'Δ', gamma: 'Γ', theta: 'Θ/j', vega: 'V/pt',
    vanna: 'Vanna', charm: 'Charm' }
  const gDigits: Record<Greek, number> = { delta: 2, gamma: 4, theta: 2, vega: 2, vanna: 3, charm: 4 }
  // PROVENANCE des Grecques de l'échéance affichée (D-044). Une Grecque calculée ne doit jamais
  // passer pour une donnée du feed : l'opérateur voit d'où elle vient (§3).
  const rows = Array.isArray(exp?.rows) ? exp!.rows : []
  const provenance = rows.length === 0 ? null
    : rows.every((r) => r.call?.greeks_source === 'INVERTED') ? { txt: 'IV inversée du prix', cls: 'text-risk-green' }
      : rows.some((r) => r.call?.greeks_source === 'INVERTED') ? { txt: 'IV inversée (partiel)', cls: 'text-risk-yellow' }
        : rows.some((r) => r.call?.greeks_source === 'SOURCE_IV') ? { txt: 'Grecques à l\u2019IV source', cls: 'text-term-dim' }
          : { txt: 'valeurs source relayées', cls: 'text-stale' }

  return (
    <Panel code="OMON" title="Chaîne d'options · skew" block="vol_surface.options_chain" accent="sony"
      right={<span className="flex items-center gap-2 text-xxs">
        {provenance && <span className={cn('font-semibold', provenance.cls)}
          title="Origine des Grecques affichées : calculées par le moteur Black-Scholes après inversion de l'IV depuis le prix de marché, calculées à l'IV du feed, ou simplement relayées.">
          {provenance.txt}</span>}
        <span className="tabular-nums text-term-faint">U {num(val?.underlying)} · ATM {num(val?.atm_strike, 0)}</span>
      </span>}>
      <div className={cn('flex h-full min-h-0 flex-col gap-0.5', fresh === 'STALE' && 'opacity-60')}>
        {/* onglets d'échéance + sélecteur de grecque (interactif) */}
        <div className="flex shrink-0 flex-wrap items-center gap-1">
          {exps.map((e, i) => (
            <button key={i} onClick={() => setExpIdx(i)}
              className={cn('rounded-sm border px-1 text-xxs tabular-nums',
                i === idx ? 'border-sony/70 text-sony' : 'border-term-border text-term-dim hover:text-term-text')}>
              {e.expiry ?? '?'}<span className="text-term-faint"> {num(e.dte, 0)}j</span>
            </button>
          ))}
          <span className="ml-auto flex items-center gap-0.5">
            {GREEKS.map((g) => (
              <button key={g} onClick={() => setGreek(g)}
                className={cn('rounded-sm border px-1 text-xxs', g === greek
                  ? 'border-router/70 text-router' : 'border-term-border text-term-dim hover:text-term-text')}>
                {gLabel[g]}
              </button>
            ))}
          </span>
        </div>

        {/* SKEW canvas (haut) */}
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
          {!noData && (
            <span className="absolute left-8 top-0 text-xxs text-term-faint">
              <span className="text-[rgb(56,189,248)]">▬ call</span>{' '}
              <span className="text-[rgb(244,114,182)]">▬ put</span> IV% · <span className="text-router">┊ ATM</span>
            </span>
          )}
        </div>

        {/* GRILLE haute densité (bas) — Call | Strike | Put */}
        <div className="min-h-0 shrink-0 overflow-auto" style={{ maxHeight: '46%' }}>
          <table className="w-full border-collapse text-right font-mono text-xxs tabular-nums">
            <thead className="sticky top-0 bg-term-panel text-term-faint">
              <tr>
                <th className="px-1 text-left font-normal">C·{gLabel[greek]}</th>
                <th className="px-1 font-normal">C·IV</th>
                <th className="px-1 text-center font-normal text-term-dim">STRIKE</th>
                <th className="px-1 font-normal">P·IV</th>
                <th className="px-1 text-left font-normal">P·{gLabel[greek]}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const atm = r.call?.moneyness === 'ATM'
                const cItm = r.call?.moneyness === 'ITM', pItm = r.put?.moneyness === 'ITM'
                return (
                  <tr key={r.strike} className={cn('border-t border-term-border/40', atm && 'bg-router/10')}>
                    {/* fond ITM discret (mur de la monnaie lu d'un coup d'œil) — redondant avec
                        la clarté du texte + la position (jamais la couleur seule §3) */}
                    <td className={cn('px-1 text-left', cItm ? 'bg-[rgba(56,189,248,0.07)] text-term-text' : 'text-term-dim')}>{num(scaled(r.call?.[greek], greek), gDigits[greek])}</td>
                    <td className={cn('px-1 text-[rgb(56,189,248)]', cItm && 'bg-[rgba(56,189,248,0.07)]')}>{pct(r.call?.iv)}</td>
                    <td className={cn('px-1 text-center', atm ? 'font-bold text-router' : 'text-term-text')}>
                      {num(r.strike, 0)}{atm && <span className="text-xxs"> ◄</span>}
                    </td>
                    <td className={cn('px-1 text-[rgb(244,114,182)]', pItm && 'bg-[rgba(244,114,182,0.07)]')}>{pct(r.put?.iv)}</td>
                    <td className={cn('px-1 text-left', pItm ? 'bg-[rgba(244,114,182,0.07)] text-term-text' : 'text-term-dim')}>{num(scaled(r.put?.[greek], greek), gDigits[greek])}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </Panel>
  )
}
