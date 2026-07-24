/** Vue ROBUSTESSE — validation quantitative de la stabilité des stratégies (D-043, tranche 3).
 *  Consomme GET /analyses/robustness = { walk_forward, monte_carlo } calculés sur les R-multiples
 *  RÉCONCILIÉS (analyse OFFLINE de recherche, HORS ContextSchema live §1 — comme PNL/RECAP).
 *  GAUCHE : verdict Walk-Forward (badge ROBUSTE / SURAJUSTEMENT + WFE + fenêtres).
 *  DROITE : distribution Monte Carlo du Max Drawdown (P50/P95/P99 vis-à-vis du seuil challenge) +
 *  probabilité d'invalidation. Code couleur §3 : VERT/ROUGE jamais seuls → glyphe + texte + position ;
 *  OR = seuil de référence. FAIL-CLOSED (§3/§8) : données insuffisantes → « DONNÉES INSUFFISANTES »,
 *  jamais un nombre fabriqué. VUE d'analyse (pas un panneau SSE), advisory : ne passe aucun ordre (§2.1). */
import { useCallback, useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Panel } from '@/components/ui/panel'

// ---------- types (miroir de GET /analyses/robustness) ----------

interface WalkForwardWindow {
  start: number; n_is: number; n_oos: number; is_profit: number; oos_profit: number
  wfe: number | null; overfit: boolean | null; reason: string
}
interface WalkForward {
  verdict: string; wfe: number | null; n_windows: number; overfit_windows: number
  overfit_ratio: number | null; is_frac: number; window: number; step: number; threshold: number
  windows: WalkForwardWindow[]
}
interface MonteCarlo {
  verdict: string; n_sims: number; n_trades: number; threshold: number | null
  max_dd_p50: number | null; max_dd_p95: number | null; max_dd_p99: number | null
  prob_exceed: number | null; mean_max_dd: number | null; seed: number | null; capped: boolean
}
interface RobustnessPayload { walk_forward: WalkForward; monte_carlo: MonteCarlo }

const POLL_MS = 15000

// Une réponse PARTIELLE (bloc manquant, JSON mutilé) faisait planter la vue — et avec elle le
// terminal entier (écran blanc, Zone 0 comprise). La forme est donc VALIDÉE avant tout rendu :
// bloc absent/non-objet → on substitue un objet fail-closed `INSUFFICIENT_DATA` (§3), jamais un
// accès sur `undefined`. Aucune valeur n'est inventée : l'absence est affichée comme telle.
const isObj = (x: unknown): x is Record<string, unknown> =>
  typeof x === 'object' && x !== null && !Array.isArray(x)

const WF_EMPTY: WalkForward = { verdict: 'INSUFFICIENT_DATA', wfe: null, n_windows: 0,
  overfit_windows: 0, overfit_ratio: null, is_frac: 0.7, window: 0, step: 0, threshold: 0.5, windows: [] }
const MC_EMPTY: MonteCarlo = { verdict: 'INSUFFICIENT_DATA', n_sims: 0, n_trades: 0, threshold: null,
  max_dd_p50: null, max_dd_p95: null, max_dd_p99: null, prob_exceed: null, mean_max_dd: null,
  seed: null, capped: false }

function normalize(raw: unknown): RobustnessPayload {
  const r = isObj(raw) ? raw : {}
  const wf = isObj(r.walk_forward) ? { ...WF_EMPTY, ...r.walk_forward } as WalkForward : WF_EMPTY
  const mc = isObj(r.monte_carlo) ? { ...MC_EMPTY, ...r.monte_carlo } as MonteCarlo : MC_EMPTY
  // un `is_frac` manquant produisait « IS NaN% » — on retombe sur la convention 70/30
  if (!Number.isFinite(wf.is_frac)) wf.is_frac = WF_EMPTY.is_frac
  if (!Number.isFinite(wf.threshold)) wf.threshold = WF_EMPTY.threshold
  return { walk_forward: wf, monte_carlo: mc }
}

// verdict Walk-Forward → glyphe + libellé + classe (jamais la couleur seule §3)
function wfBadge(verdict: string): { glyph: string; label: string; cls: string } {
  switch (verdict) {
    case 'ROBUST': return { glyph: '✓', label: 'ROBUSTE', cls: 'border-risk-green/60 text-risk-green' }
    case 'OVERFIT_DETECTED': return { glyph: '⚠', label: 'SURAJUSTEMENT', cls: 'border-risk-red/60 text-risk-red' }
    case 'IS_UNPROFITABLE': return { glyph: '∅', label: 'IS NON PROFITABLE', cls: 'border-risk-yellow/50 text-risk-yellow' }
    default: return { glyph: '·', label: 'DONNÉES INSUFFISANTES', cls: 'border-absent/50 text-absent' }
  }
}

// probabilité d'invalidation → bande de risque (glyphe + texte + couleur, jamais seule §3)
function probBand(p: number | null): { glyph: string; label: string; cls: string } {
  if (p === null || !Number.isFinite(p)) return { glyph: '·', label: 'indéterminée', cls: 'text-term-dim' }
  if (p < 0.10) return { glyph: '✓', label: 'faible', cls: 'text-risk-green' }
  if (p < 0.30) return { glyph: '⚠', label: 'modérée', cls: 'text-risk-yellow' }
  return { glyph: '▲', label: 'élevée', cls: 'text-risk-red' }
}

const pctOf = (v: number | null): string =>
  v === null || !Number.isFinite(v) ? '·' : (v * 100).toFixed(1) + ' %'
const rOf = (v: number | null): string =>
  v === null || !Number.isFinite(v) ? '·' : fmtNum(v, 2) + ' R'
// Un run BORNÉ (n_sims réduit par le budget CPU) doit montrer son compte EXACT : c'est là que
// l'information est critique. Sous 1000, pas d'arrondi en « k » (qui affichait « 0k sims »).
const simsOf = (n: number): string =>
  !Number.isFinite(n) ? '·' : n >= 1000 ? Math.round(n / 1000) + 'k sims' : n + ' sims'

// Bande de fenêtres BORNÉE : le nombre de fenêtres croît avec l'historique et devient vite un mur
// illisible ; on affiche les plus récentes et on ANNONCE le reste (jamais de troncature muette §8).
const MAX_STRIP = 48

function useRobustness() {
  const [data, setData] = useState<RobustnessPayload | null>(null)
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [okTs, setOkTs] = useState<number | null>(null)   // horodatage du dernier succès
  const reqSeq = useRef(0)
  const inFlight = useRef(false)
  const refresh = useCallback(async () => {
    // Backpressure : chaque appel déclenche un calcul Monte Carlo complet côté serveur. Une rafale
    // de clics en lançait autant en parallèle → on IGNORE tant qu'une requête est en vol.
    if (inFlight.current) return
    inFlight.current = true; setBusy(true)
    const seq = ++reqSeq.current
    try {
      const d = normalize(await api.analysesRobustness())   // forme validée avant tout rendu
      if (seq === reqSeq.current) { setData(d); setFailed(false); setOkTs(Date.now()) }
    } catch {
      if (seq === reqSeq.current) setFailed(true)   // conserve l'affichage mais le marque PÉRIMÉ
    } finally {
      inFlight.current = false; setBusy(false)
    }
  }, [])
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), POLL_MS)
    return () => { reqSeq.current++; window.clearInterval(timer) }
  }, [refresh])
  return { data, failed, busy, okTs, refresh }
}

// ---------- Walk-Forward (colonne gauche) ----------

function WalkForwardCard({ wf }: { wf: WalkForward }) {
  const b = wfBadge(wf.verdict)
  const insufficient = wf.verdict === 'INSUFFICIENT_DATA'
  const all = Array.isArray(wf.windows) ? wf.windows : []
  const shown = all.slice(-MAX_STRIP)                 // les plus RÉCENTES (fin du tableau)
  const hidden = all.length - shown.length
  return (
    <section className="flex min-h-0 flex-1 flex-col gap-2 border border-term-border bg-term-panel2 p-3">
      <header className="flex items-baseline justify-between">
        <h3 className="text-xs font-bold uppercase tracking-wide text-term-text">Walk-Forward</h3>
        <span className="text-xxs text-term-faint">IS {Math.round(wf.is_frac * 100)}% / OOS {Math.round((1 - wf.is_frac) * 100)}%</span>
      </header>
      <div className={cn('flex items-center gap-2 border px-2 py-2', b.cls)}>
        <span className="text-lg leading-none" aria-hidden>{b.glyph}</span>
        <span className="text-sm font-bold tracking-wide">{b.label}</span>
        <span className="ml-auto tabular-nums text-xs text-term-text">
          WFE <span className="font-bold">{wf.wfe === null ? '·' : fmtNum(wf.wfe, 2)}</span>
          <span className="text-term-faint"> / seuil {fmtNum(wf.threshold, 2)}</span>
        </span>
      </div>
      {insufficient ? (
        <p className="absent-pulse py-6 text-center font-mono text-xs font-bold text-absent">DONNÉES INSUFFISANTES</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xxs">
            <Row label="Fenêtres analysées" value={String(wf.n_windows)} />
            <Row label="Fenêtres surajustées" value={`${wf.overfit_windows} / ${wf.n_windows}`}
              danger={wf.overfit_windows > 0} />
          </div>
          {/* Strip par fenêtre. Ordre : `start` CROISSANT côté moteur ⇒ `windows[0]` couvre les trades
              les plus ANCIENS — le libellé doit donc dire « ancien → récent », sinon l'opérateur lit
              sa dégradation temporelle à l'envers. Affichage borné aux dernières, reste annoncé. */}
          <div className="mt-1">
            <span className="mb-1 block text-xxs uppercase text-term-faint">
              Fenêtres (ancien → récent)
              {hidden > 0 && <span className="normal-case text-term-dim"> · {hidden} plus anciennes masquées</span>}
            </span>
            <div className="flex flex-wrap gap-1">
              {shown.length === 0 && <span className="text-xxs text-term-dim">—</span>}
              {shown.map((w, i) => (
                <span key={hidden + i} title={`fenêtre @${w.start} · WFE ${w.wfe === null ? '·' : fmtNum(w.wfe, 2)}${w.reason ? ` · ${w.reason}` : ''}`}
                  className={cn('inline-flex h-5 min-w-[2.1rem] items-center justify-center border px-1 text-xxs font-bold tabular-nums',
                    w.overfit === true ? 'border-risk-red/60 text-risk-red'
                      : w.overfit === false ? 'border-risk-green/50 text-risk-green'
                        : 'border-term-border text-term-dim')}>
                  {w.wfe === null ? '·' : fmtNum(w.wfe, 1)}
                </span>
              ))}
            </div>
          </div>
        </>
      )}
      <p className="mt-auto text-xxs leading-snug text-term-faint">
        WFE = rendement/trade OOS ÷ IS. &lt; {fmtNum(wf.threshold, 2)} ⇒ surajustement (le passé ne se
        généralise pas). Advisory — n'influe sur aucun ordre (§2.1).
      </p>
    </section>
  )
}

// ---------- Monte Carlo (colonne droite) ----------

function MonteCarloCard({ mc }: { mc: MonteCarlo }) {
  const insufficient = mc.verdict !== 'OK'
  const thr = mc.threshold
  const band = probBand(mc.prob_exceed)
  // échelle : 0 → max(P99, seuil)·1.2 ; zone de danger au-delà du seuil (rouge léger)
  const scaleMax = Math.max(mc.max_dd_p99 ?? 0, thr ?? 0) * 1.2 || 1
  const pos = (v: number | null): number =>
    v === null || !Number.isFinite(v) ? 0 : Math.max(0, Math.min(100, (v / scaleMax) * 100))
  const marks: { key: string; label: string; v: number | null }[] = [
    { key: 'p50', label: 'P50', v: mc.max_dd_p50 },
    { key: 'p95', label: 'P95', v: mc.max_dd_p95 },
    { key: 'p99', label: 'P99', v: mc.max_dd_p99 },
  ]
  // Sur une distribution dégénérée (P50 = P95 = P99 — perte totale en un jour, ou aucun drawdown)
  // les trois étiquettes tombent au même point. Le TRAIT reste à la position VRAIE (honnêteté §3) ;
  // seule l'ÉTIQUETTE glisse d'un écart minimal pour rester lisible.
  const LABEL_GAP = 8
  const labelPos = ((): number[] => {
    const out = marks.map((m) => pos(m.v))
    for (let i = 1; i < out.length; i++) out[i] = Math.max(out[i], out[i - 1] + LABEL_GAP)
    const over = out[out.length - 1] - 96
    if (over > 0) for (let i = 0; i < out.length; i++) out[i] -= over      // recale dans le cadre
    return out.map((x) => Math.max(4, Math.min(96, x)))
  })()
  return (
    <section className="flex min-h-0 flex-1 flex-col gap-2 border border-term-border bg-term-panel2 p-3">
      <header className="flex items-baseline justify-between">
        <h3 className="text-xs font-bold uppercase tracking-wide text-term-text">Monte Carlo · Max Drawdown</h3>
        <span className="text-xxs text-term-faint"
          title={mc.capped ? 'budget CPU atteint : nombre de simulations réduit (résultat valide, précision moindre)' : undefined}>
          {insufficient ? '—' : simsOf(mc.n_sims)}{mc.capped ? ' (borné)' : ''}
        </span>
      </header>
      {insufficient ? (
        <p className="absent-pulse py-6 text-center font-mono text-xs font-bold text-absent">DONNÉES INSUFFISANTES</p>
      ) : (
        <>
          {/* probabilité d'invalidation du challenge — métrique clé */}
          <div className="flex items-center gap-2 border border-term-border px-2 py-2">
            <span className="text-xxs uppercase text-term-faint">P(atteindre le DD max {rOf(thr)})</span>
            <span className={cn('ml-auto flex items-baseline gap-1.5 tabular-nums', band.cls)}>
              <span aria-hidden>{band.glyph}</span>
              <span className="text-base font-bold">{pctOf(mc.prob_exceed)}</span>
              <span className="text-xxs">{band.label}</span>
            </span>
          </div>
          {/* échelle horizontale : zone de danger (≥ seuil) + trait OR du seuil + marqueurs P50/95/99 */}
          <div className="mt-1">
            <div className="relative h-9 border border-term-border bg-term-panel">
              {thr !== null && Number.isFinite(thr) && (
                <>
                  <div className="absolute inset-y-0 bg-risk-red/10"
                    style={{ left: `${pos(thr)}%`, right: 0 }} aria-hidden />
                  <div className="absolute inset-y-0 w-px bg-router" style={{ left: `${pos(thr)}%` }} aria-hidden />
                  <span className="absolute -top-0.5 translate-x-1 text-xxs font-bold text-router"
                    style={{ left: `${pos(thr)}%` }}>seuil {rOf(thr)}</span>
                </>
              )}
              {marks.map((m, i) => {
                const over = m.v !== null && thr !== null && m.v >= thr
                return (
                  <div key={m.key} aria-hidden>
                    {/* trait = position RÉELLE de la valeur */}
                    <div className={cn('absolute top-0 h-4 w-px', over ? 'bg-risk-red' : 'bg-term-text')}
                      style={{ left: `${pos(m.v)}%` }} />
                    {/* étiquette = position dé-chevauchée (lisible même si P50 = P95 = P99) */}
                    <span className={cn('absolute bottom-0.5 -translate-x-1/2 text-[9px] font-bold tabular-nums',
                      over ? 'text-risk-red' : 'text-term-dim')} style={{ left: `${labelPos[i]}%` }}>{m.label}</span>
                  </div>
                )
              })}
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {marks.map((m) => {
              const over = m.v !== null && thr !== null && m.v >= thr
              return (
                <div key={m.key} className="border border-term-border px-1 py-1">
                  <span className="block text-xxs uppercase text-term-faint">{m.label}</span>
                  <span className={cn('block tabular-nums text-sm font-bold', over ? 'text-risk-red' : 'text-term-text')}>
                    {rOf(m.v)}{over && <span className="ml-0.5 text-xxs" aria-hidden>▲</span>}
                  </span>
                </div>
              )
            })}
          </div>
          <p className="mt-auto text-xxs leading-snug text-term-faint">
            {mc.n_trades} trades réconciliés · bootstrap avec remise · moyenne {rOf(mc.mean_max_dd)}.
            Un P95/P99 ≥ seuil (▲) = risque réel d'invalidation. Advisory (§2.1).
          </p>
        </>
      )}
    </section>
  )
}

function Row({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="truncate text-term-faint">{label}</span>
      <span className={cn('shrink-0 tabular-nums font-bold', danger ? 'text-risk-red' : 'text-term-text')}>{value}</span>
    </div>
  )
}

export function RobustnessView() {
  const { data, failed, busy, okTs, refresh } = useRobustness()
  // Un échec APRÈS un succès laissait les anciens chiffres à l'écran sans le dire : un drawdown
  // périmé se lisait comme courant (§3). Les données restent visibles — mais marquées PÉRIMÉ.
  const stale = failed && data !== null

  return (
    <div className="flex min-h-0 flex-1 flex-col p-1.5">
      <Panel code="ROBUST" title="Robustesse — Walk-Forward & Monte Carlo" accent="none"
        block="projection · /analyses/robustness" className="min-h-0 flex-1"
        right={
          <button onClick={() => void refresh()} disabled={busy}
            title={busy ? 'calcul en cours…' : "Rafraîchir l'analyse"}
            className={cn('inline-flex items-center gap-1 border border-term-border px-1.5 py-0.5 text-xxs font-semibold uppercase',
              busy ? 'cursor-wait text-term-faint' : 'text-term-dim hover:text-term-text')}>
            <RefreshCw className={cn('h-3 w-3', busy && 'animate-spin')} /> maj
          </button>
        }>
        {data === null ? (
          <p className="grid h-full place-items-center font-mono text-xs text-term-dim">
            {failed ? 'analyse indisponible — flux backend interrompu' : 'chargement de l’analyse…'}
          </p>
        ) : (
          <div className={cn('flex min-h-0 flex-1 flex-col', stale && 'opacity-70')}>
            {stale && (
              <p className="flex shrink-0 items-center gap-1.5 border border-stale/50 bg-stale/10 px-2 py-1 text-xxs font-bold text-stale">
                <span aria-hidden>⚠</span> PÉRIMÉ — le calcul n'a pas pu être rafraîchi
                {okTs !== null && <span className="font-normal"> · dernier succès {new Date(okTs).toLocaleTimeString('fr-CA')}</span>}
                <span className="ml-auto font-normal">relancer avec « maj »</span>
              </p>
            )}
            <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-auto p-2 lg:grid-cols-2">
              <WalkForwardCard wf={data.walk_forward} />
              <MonteCarloCard mc={data.monte_carlo} />
            </div>
          </div>
        )}
      </Panel>
    </div>
  )
}
