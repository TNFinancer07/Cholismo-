/** B4 — Unified Signal Output (`unified_signal_output`) — PANNEAU PREMIER (Router, or).
 *  Barre segmentée 35/25/20/15/5 ; bandeau explicite si dégradé (macro non calibrée → /80) ;
 *  Go/No-Go écrivent un DecisionEvent — JAMAIS un ordre. Countdown C3 visible en décision
 *  pendante ; à expiration le backend écrit NO_GO reason=timeout. */
import { useState } from 'react'
import { AlertTriangle, TimerReset } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Sparkline } from '@/components/Sparkline'
import { api } from '@/lib/api'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'
import { effectivePhase0, serverNow, useTerminal } from '@/store/terminal'

const SEGMENTS = [
  { key: 'structure', label: 'Structure', weight: 35, cls: 'bg-sony/70' },
  { key: 'order_flow', label: 'Order flow', weight: 25, cls: 'bg-sony/40' },
  { key: 'macro', label: 'Macro', weight: 20, cls: 'bg-youssef/60' },
  { key: 'sentiment', label: 'Sentiment', weight: 15, cls: 'bg-youssef/35' },
  { key: 'quality', label: 'Qualité', weight: 5, cls: 'bg-term-dim/60' },
] as const

function Countdown() {
  const window_ = useTerminal((s) => s.unified_signal_output?.decision_window)
  const nowTick = useTerminal((s) => s.nowTick)
  const clockOffset = useTerminal((s) => s.clockOffset)
  if (!window_?.open || window_.deadline_ts === null) return null
  const remaining = Math.max(0, window_.deadline_ts - serverNow({ nowTick, clockOffset }))
  const critical = remaining <= 15
  return (
    <div className={cn('mt-1.5 flex items-center justify-between border px-2 py-1',
      critical ? 'border-risk-red countdown-critical' : 'border-router/50')}
      role="timer" aria-label="Countdown anti-paralysie C3">
      <span className="inline-flex items-center gap-1.5 text-xxs uppercase tracking-wide text-term-dim">
        <TimerReset size={11} aria-hidden />
        C3 anti-paralysie — expiration = NO-GO auto (reason=timeout)
      </span>
      <span className={cn('text-base font-black tabular-nums', critical ? 'text-risk-red' : 'text-router')}>
        {Math.floor(remaining)}s
      </span>
    </div>
  )
}

export function UnifiedSignalPanel() {
  const signal = useTerminal((s) => s.unified_signal_output)
  const operator = useTerminal((s) => s.operator)
  const selfcheckPresent = useTerminal((s) => s.selfcheckPresent)
  const { phase0 } = useTerminal((s) => effectivePhase0(s))
  const [busy, setBusy] = useState(false)

  const pending = signal?.decision_window.open ?? false
  const canGo = pending && phase0 === 'OPEN' && selfcheckPresent

  async function decide(decision: 'GO' | 'NO_GO') {
    setBusy(true)
    try {
      await api.postDecision(operator, decision)
      useTerminal.getState().set({ lastError: null })
    } catch (err) {
      useTerminal.getState().set({ lastError: (err as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const breakdown = signal?.breakdown

  return (
    <Panel code="B4" title="Signal unifié" block="unified_signal_output" accent="router">
      {signal?.degraded && (
        <div className="mb-1.5 flex items-center gap-1.5 border border-risk-yellow/60 bg-risk-yellow/10 px-1.5 py-0.5 text-xxs font-semibold uppercase text-risk-yellow"
          role="alert">
          <AlertTriangle size={11} aria-hidden />
          Macro non calibrée — signal partiel /80
        </div>
      )}

      <div className="flex items-baseline justify-between">
        <span className="flex items-baseline gap-3">
          <span className="text-3xl font-black tabular-nums text-term-text">
            {signal?.score === null || signal?.score === undefined ? '—' : fmtNum(signal.score, 1)}
            <span className="text-sm text-term-dim">/100</span>
          </span>
          <Sparkline seriesKey="score" width={110} height={22} stroke="#f0b429" />
        </span>
        <Badge variant={signal?.decision === 'GO' ? 'green' : signal?.decision === 'NO_GO' ? 'red' : 'router'}>
          {signal?.decision === 'PENDING' && pending ? 'DÉCISION PENDANTE' : signal?.decision ?? '—'}
        </Badge>
      </div>

      {/* Barre segmentée par contribution — largeur = poids, remplissage = contribution */}
      <div className="mt-1.5 flex h-4 w-full gap-px" role="img" aria-label="Décomposition du signal">
        {SEGMENTS.map((seg) => {
          const contribution = breakdown?.[seg.key] ?? null
          const fillPct = contribution === null ? 0 : Math.min(100, (contribution / seg.weight) * 100)
          return (
            <div key={seg.key} style={{ width: `${seg.weight}%` }}
              className="relative overflow-hidden border border-term-border bg-term-grid"
              title={`${seg.label} ${contribution === null ? '— (N/C)' : `${fmtNum(contribution, 1)}/${seg.weight}`}`}>
              <div className={cn('h-full', seg.cls)} style={{ width: `${fillPct}%` }} />
              {contribution === null && (
                <span className="absolute inset-0 grid place-items-center text-xxs text-term-faint">N/C</span>
              )}
            </div>
          )
        })}
      </div>
      <div className="mt-0.5 flex justify-between text-xxs text-term-dim">
        {SEGMENTS.map((seg) => {
          const contribution = breakdown?.[seg.key] ?? null
          return (
            <span key={seg.key} style={{ width: `${seg.weight}%` }} className="truncate">
              {seg.label} {contribution === null ? '—' : `${fmtNum(contribution, 1)}/${seg.weight}`}
            </span>
          )
        })}
      </div>

      <Countdown />

      {/* Décision humaine — écrit un event, ne passe JAMAIS d'ordre (CLAUDE §2.1) */}
      <div className="mt-2 flex items-center gap-2">
        <Button variant="go" size="lg" className="flex-1" disabled={!canGo || busy}
          onClick={() => void decide('GO')}
          title={!pending ? 'Aucune décision pendante'
            : phase0 !== 'OPEN' ? 'Phase 0 BLOQUÉ — verrou déterministe'
            : !selfcheckPresent ? 'Self-check C5 obligatoire (touche S)'
            : 'GO (touche G) — écrit un DecisionEvent'}>
          GO <kbd className="rounded border border-risk-green/50 px-1">G</kbd>
        </Button>
        <Button variant="nogo" size="lg" className="flex-1" disabled={!pending || busy}
          onClick={() => void decide('NO_GO')}
          title="NO-GO (touche N) — écrit un DecisionEvent">
          NO-GO <kbd className="rounded border border-risk-red/50 px-1">N</kbd>
        </Button>
      </div>
      <p className="mt-1 text-center text-xxs text-term-faint">
        décision humaine → event immuable · aucune exécution d'ordre
      </p>
    </Panel>
  )
}
