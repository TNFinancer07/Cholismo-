/** Vue RECAP — le cockpit de session (brainstorm « Récapitulatif », D-023).
 *
 *  Hiérarchie à deux étages (tension 01 arbitrée) : le NIVEAU RÉFLEXE (P&L, risque
 *  restant, feu météo, fenêtres) est toujours visible et lisible < 3 s ; le NIVEAU
 *  ANALYSE (jauges, equity, split stratégies, modules, agents) se déplie à la demande.
 *  Optimisé : la projection /recap n'est interrogée que lorsque la vue est montée
 *  (poll léger 5 s) ; les tuiles de marché lisent le store SSE existant par sélecteurs
 *  étroits — aucun canal supplémentaire. Seuls P&L et risque s'animent (tension 03) :
 *  transitions CSS lissées, le reste se met à jour silencieusement. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, CircleDollarSign, CloudSun,
  Gauge, HeartPulse, TimerReset } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtAge, fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import { RiskGlyph } from '@/components/RiskGlyph'
import type { RecapPayload } from '@/types/schema'

const POLL_MS = 5000

function useRecap(granularity: string) {
  const [data, setData] = useState<RecapPayload | null>(null)
  const refresh = useCallback(async () => {
    try { setData(await api.recap(granularity) as RecapPayload) } catch { /* canal muet couvre */ }
  }, [granularity])
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [refresh])
  return data
}

const GRANULARITY_LABELS: Record<string, string> = {
  session: 'SESSION', week: 'SEMAINE', month: 'MOIS',
}

/** Bandeau P&L vivant — LE chiffre lisible à 2 mètres. Lissé (transition CSS),
 *  1 décimale en R (« trop de décimales = du bruit »). */
function PnlBanner({ recap }: { recap: RecapPayload }) {
  const { pnl } = recap
  const tone = pnl.n_trades === 0 ? 'text-term-dim'
    : pnl.r_total > 0 ? 'text-risk-green' : pnl.r_total < 0 ? 'text-risk-red' : 'text-router'
  return (
    <div className="flex items-baseline gap-4">
      <span className={cn('font-mono text-5xl font-black tabular-nums leading-none',
        'transition-colors duration-700', tone)}>
        {fmtSigned(pnl.r_total, 1)} R
      </span>
      <span className={cn('font-mono text-xl tabular-nums transition-colors duration-700', tone)}>
        {fmtSigned(pnl.usd, 0)} $
      </span>
      <span className="text-xxs text-term-faint">
        {pnl.n_trades} trade{pnl.n_trades > 1 ? 's' : ''} · 1 R = {fmtNum(recap.r_unit_usd, 0)} $
      </span>
    </div>
  )
}

/** Jauge de risque consommé + risk-clock (« temps de jeu restant »). */
function RiskGaugeBlock({ recap }: { recap: RecapPayload }) {
  const { risk } = recap
  const pct = risk.consumed_pct ?? 0
  const zone = pct >= 80 ? 'bg-risk-red' : pct >= 50 ? 'bg-risk-yellow' : 'bg-risk-green'
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center justify-between text-xxs uppercase text-term-faint">
        <span className="inline-flex items-center gap-1"><Gauge size={11} aria-hidden />risque consommé (session)</span>
        <span className="font-mono tabular-nums text-term-dim">
          {fmtNum(risk.consumed_r, 1)} / {fmtNum(risk.max_r, 1)} R
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden border border-term-border bg-term-bg"
        role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn('h-full transition-all duration-700', zone)} style={{ width: `${pct}%` }} />
      </div>
      <div className="flex items-center gap-2 text-xxs">
        <TimerReset size={11} className="text-term-faint" aria-hidden />
        {risk.lockout.active ? (
          <span className="font-bold text-risk-red">LOCKOUT ACTIF — {risk.lockout.rule}</span>
        ) : risk.risk_clock_trades_left !== null ? (
          <span className="text-term-dim">
            risk-clock : ~<b className="font-mono text-term-text">{risk.risk_clock_trades_left}</b> trade(s)
            au rythme de perte courant ({fmtNum(risk.avg_loss_r, 2)} R)
          </span>
        ) : (
          <span className="text-term-faint">risk-clock : aucune perte n'a encore défini le rythme</span>
        )}
      </div>
    </div>
  )
}

/** Feu météo — synthèse unique, même arbitrage que la console (jamais couleur seule). */
function WeatherBlock({ recap }: { recap: RecapPayload }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="inline-flex items-center gap-1 text-xxs uppercase text-term-faint">
        <CloudSun size={11} aria-hidden />météo de trade
      </span>
      <RiskGlyph level={recap.weather.level} label={`${recap.weather.level} · ${recap.weather.action}`} size={16} />
      <ul className="space-y-0.5 text-xxs text-term-dim">
        {recap.weather.reasons.length === 0 && <li>conditions alignées avec les stratégies</li>}
        {recap.weather.reasons.map((reason) => <li key={reason} className="truncate">· {reason}</li>)}
      </ul>
    </div>
  )
}

function fmtCountdown(seconds: number | null): string {
  if (seconds === null) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** Horloge de session — fenêtres SVS/MR, compte à rebours avant ouverture. */
function WindowsBlock({ recap }: { recap: RecapPayload }) {
  const rows = [
    { id: 'SVS', label: 'SVS 09h30–11h00', win: recap.windows.svs },
    { id: 'MR', label: 'MR 15h30–17h00', win: recap.windows.mean_reversion },
  ]
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-xxs uppercase text-term-faint">fenêtres d'exécution (Montréal)</span>
      {rows.map(({ id, label, win }) => (
        <div key={id} className={cn('flex items-center justify-between gap-2 border px-1.5 py-0.5',
          win.state === 'OUVERTE' ? 'border-sony/60 bg-sony/5' : 'border-term-border')}>
          <span className={cn('text-xxs font-semibold',
            win.state === 'OUVERTE' ? 'text-sony' : 'text-term-dim')}>{label}</span>
          <span className="font-mono text-xxs tabular-nums text-term-dim">
            {win.state === 'OUVERTE'
              ? <>ferme dans <b className="text-term-text">{fmtCountdown(win.closes_in_s)}</b></>
              : <>s'ouvre dans <b className="text-term-text">{fmtCountdown(win.opens_in_s)}</b></>}
          </span>
        </div>
      ))}
    </div>
  )
}

/** Mini equity curve — forme seule, zéro chrome (la pente raconte tout). */
function EquityCurve({ points }: { points: number[] }) {
  if (points.length < 2) {
    return <span className="text-xxs text-term-faint">equity : moins de 2 trades sur la période</span>
  }
  const width = 260; const height = 42
  const min = Math.min(0, ...points); const max = Math.max(0, ...points)
  const span = max - min || 1
  const step = width / (points.length - 1)
  const y = (v: number) => height - 3 - ((v - min) / span) * (height - 6)
  const path = points.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const last = points[points.length - 1]
  return (
    <svg width={width} height={height} role="img" aria-label="courbe d'equity de la période">
      <line x1="0" x2={width} y1={y(0)} y2={y(0)} stroke="#3d4a5c" strokeDasharray="2 3" strokeWidth="0.5" />
      <path d={path} fill="none" strokeWidth="1.25"
        stroke={last >= 0 ? '#34d399' : '#f87171'} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/** P&L attribué par stratégie — barre empilée signée. */
function StrategySplit({ recap }: { recap: RecapPayload }) {
  const split = recap.strategy_split
  if (split.length === 0) return <span className="text-xxs text-term-faint">aucun trade sur la période</span>
  const total = split.reduce((acc, s) => acc + Math.abs(s.r_total), 0) || 1
  return (
    <div className="flex flex-col gap-1">
      <div className="flex h-3 w-full overflow-hidden border border-term-border" role="img"
        aria-label="répartition du P&L par stratégie">
        {split.map((s) => (
          <div key={s.strategy_id} title={`${s.label} : ${fmtSigned(s.r_total, 2)} R`}
            className={cn(s.r_total >= 0 ? 'bg-risk-green/70' : 'bg-risk-red/70',
              s.accent === 'youssef' && 'opacity-80')}
            style={{ width: `${(100 * Math.abs(s.r_total)) / total}%` }} />
        ))}
      </div>
      <ul className="space-y-0.5">
        {split.map((s) => (
          <li key={s.strategy_id} className="flex items-center justify-between gap-2 text-xxs">
            <span className={cn('truncate', s.accent === 'youssef' ? 'text-youssef' : 'text-sony')}>
              {s.label}
            </span>
            <span className={cn('font-mono tabular-nums',
              s.r_total > 0 ? 'text-risk-green' : s.r_total < 0 ? 'text-risk-red' : 'text-term-dim')}>
              {fmtSigned(s.r_total, 2)} R · {s.n_trades}t
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const MODULE_TONES: Record<string, string> = {
  'ARMÉ': 'text-risk-green', 'ÉLIGIBLE': 'text-risk-green', 'CALIBRÉ': 'text-risk-green',
  'SURVEILLANCE': 'text-risk-yellow', 'NON CALIBRÉ': 'text-risk-yellow',
  'BLOQUÉ': 'text-risk-red', 'BLOQUÉE': 'text-risk-red', 'CRITIQUE': 'text-risk-red',
  'ABSENT': 'text-risk-red', 'MUET': 'text-risk-red',
}

/** Grille modules — un état muet = un état dangereux : chaque tuile porte SA raison,
 *  et « POURQUOI ? » déplie les gates réelles de la stratégie (aucun toggle destructif
 *  ici — la lecture est gratuite, le danger se mérite ailleurs, tension 02). */
function ModulesGrid({ recap }: { recap: RecapPayload }) {
  const [openId, setOpenId] = useState<string | null>(null)
  return (
    <div className="grid grid-cols-1 gap-1 md:grid-cols-2">
      {recap.modules.map((m) => (
        <div key={m.id} className="border border-term-border bg-term-panel2 px-1.5 py-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-xxs font-semibold text-term-text">{m.label}</span>
            <span className={cn('shrink-0 text-xxs font-black', MODULE_TONES[m.state] ?? 'text-term-dim')}>
              {m.state}
            </span>
          </div>
          <p className="truncate text-xxs text-term-dim" title={m.reason}>{m.reason}</p>
          {m.gates && m.gates.length > 0 && (
            <button className="mt-0.5 inline-flex items-center gap-0.5 text-xxs text-router hover:underline"
              onClick={() => setOpenId(openId === m.id ? null : m.id)}
              aria-expanded={openId === m.id}>
              {openId === m.id ? <ChevronDown size={10} aria-hidden /> : <ChevronRight size={10} aria-hidden />}
              pourquoi {m.state === 'ÉLIGIBLE' ? 'éligible' : 'pas de signal'} ?
            </button>
          )}
          {openId === m.id && m.gates && (
            <ul className="mt-0.5 space-y-0.5 border-t border-term-border pt-0.5">
              {m.gates.map((g) => (
                <li key={g.name} className="flex items-center justify-between gap-2 text-xxs">
                  <span className="truncate text-term-dim">{g.name}</span>
                  <span className={cn('shrink-0 font-mono font-bold',
                    g.status === 'PASS' ? 'text-risk-green'
                      : g.status === 'MANUAL' ? 'text-term-faint' : 'text-risk-red')}
                    title={g.detail}>{g.status}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}

/** Pouls des agents IA — un agent silencieux trop longtemps vire au jaune/rouge. */
function AgentsPulse({ recap }: { recap: RecapPayload }) {
  return (
    <div className="flex flex-wrap gap-1">
      {recap.agents.map((a) => (
        <span key={a.provider} className={cn('inline-flex items-center gap-1 border px-1.5 py-0.5 text-xxs',
          a.state === 'OK' ? 'border-risk-green/50 text-risk-green'
            : a.state === 'INACTIF' ? 'border-term-border text-term-faint'
            : 'border-risk-yellow/50 text-risk-yellow')}>
          <HeartPulse size={10} aria-hidden />
          <b className="uppercase">{a.provider}</b>
          <span className="text-term-dim">{a.detail}{a.age_s !== null && ` · ${fmtAge(a.age_s)}`}</span>
        </span>
      ))}
    </div>
  )
}

export function RecapView() {
  const [granularity, setGranularity] = useState('session')
  const [analysisOpen, setAnalysisOpen] = useState(true)
  const recap = useRecap(granularity)
  const lastError = useTerminal((s) => s.lastError)

  const stats = useMemo(() => recap === null ? [] : [
    { label: 'win rate', value: recap.pnl.win_rate_pct === null ? '—' : `${fmtNum(recap.pnl.win_rate_pct, 1)} %` },
    { label: 'expectancy', value: recap.pnl.expectancy_r === null ? '—' : `${fmtSigned(recap.pnl.expectancy_r, 2)} R` },
    { label: 'drawdown max', value: `${fmtNum(recap.pnl.drawdown_r, 2)} R`,
      warn: recap.pnl.drawdown_r >= recap.risk.max_drawdown_r_day },
    { label: 'W / L', value: `${recap.pnl.wins} / ${recap.pnl.losses}` },
  ], [recap])

  if (recap === null) {
    return <div className="grid flex-1 place-items-center text-xs text-term-faint">chargement du cockpit…</div>
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-auto p-1.5">
      {/* ---- NIVEAU RÉFLEXE — lisible < 3 s, toujours visible ---- */}
      <Panel code="RECAP" title="Cockpit de session — niveau réflexe" accent="router"
        block="projection decision log + journal + schéma"
        right={
          <div className="flex items-center gap-0.5" role="tablist" aria-label="granularité">
            {recap.granularities.map((g) => (
              <button key={g} role="tab" aria-selected={granularity === g}
                className={cn('border px-1.5 text-xxs font-semibold uppercase',
                  granularity === g ? 'border-router text-router' : 'border-term-border text-term-dim hover:text-term-text')}
                onClick={() => setGranularity(g)}>
                {GRANULARITY_LABELS[g] ?? g}
              </button>
            ))}
          </div>
        }>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div className="flex flex-col gap-2">
            <PnlBanner recap={recap} />
            <EquityCurve points={recap.pnl.equity_curve} />
            {recap.signal_degraded && (
              <span className="inline-flex items-center gap-1 text-xxs text-risk-yellow">
                <AlertTriangle size={10} aria-hidden /> signal DÉGRADÉ /80 — macro NON CALIBRÉ
              </span>
            )}
          </div>
          <RiskGaugeBlock recap={recap} />
          <WeatherBlock recap={recap} />
          <WindowsBlock recap={recap} />
        </div>
      </Panel>

      {/* ---- NIVEAU ANALYSE — dépliable, le débrief l'ouvre ---- */}
      <button className="flex items-center gap-1 text-xxs uppercase text-term-dim hover:text-term-text"
        onClick={() => setAnalysisOpen(!analysisOpen)} aria-expanded={analysisOpen}>
        {analysisOpen ? <ChevronDown size={11} aria-hidden /> : <ChevronRight size={11} aria-hidden />}
        niveau analyse — jauges · split stratégies · modules · agents
      </button>

      {analysisOpen && (
        <div className="grid grid-cols-1 gap-1.5 lg:grid-cols-3">
          <Panel code="R1" title="Performance" block="journal trade_locked (projection)">
            <div className="grid grid-cols-2 gap-1.5">
              {stats.map((s) => (
                <div key={s.label} className="border border-term-border bg-term-panel2 px-1.5 py-1">
                  <span className="block text-xxs uppercase text-term-faint">{s.label}</span>
                  <span className={cn('font-mono text-sm font-bold tabular-nums',
                    'warn' in s && s.warn ? 'text-risk-red' : 'text-term-text')}>{s.value}</span>
                </div>
              ))}
            </div>
            <div className="mt-2">
              <span className="mb-0.5 block text-xxs uppercase text-term-faint">
                <CircleDollarSign size={10} className="mr-1 inline" aria-hidden />p&l par stratégie
              </span>
              <StrategySplit recap={recap} />
            </div>
          </Panel>

          <Panel code="R2" title="État des modules" block="phase0 + s1_state.strategies + extras">
            <ModulesGrid recap={recap} />
          </Panel>

          <Panel code="R3" title="Pouls des agents IA" block="ai_calls (event store)">
            <AgentsPulse recap={recap} />
            <p className="mt-2 text-xxs text-term-faint">
              Groq = advisory Phase 0 (&lt; 100 ms, fail-closed) · Claude = scoring périodique hors
              hot path · Gemini = audit tous les 20 trades. Aucun agent n'est dans le chemin de
              décision live (CLAUDE §2.8).
            </p>
          </Panel>
        </div>
      )}

      {lastError && <p className="text-xxs text-risk-red">{lastError}</p>}
    </div>
  )
}
