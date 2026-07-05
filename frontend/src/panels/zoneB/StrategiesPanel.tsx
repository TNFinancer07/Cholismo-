/** S1S — Les DEUX stratégies d'exécution réelles de Sony (`s1_state.strategies`).
 *  1. SVS — Structural Vacuum Squeeze (breakout LVN, matin) — reference/sony/SVS…
 *  2. Mean Reversion — Piège d'Absorption v5.8 (après-midi) — reference/sony/strategie2…
 *  Gates évalués sur les données réellement câblées ; MANUAL/ABSENT affichés tels quels. */
import { Crosshair, Magnet } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import type { ExecutionStrategy, StrategyGate } from '@/types/schema'

const GATE_STYLE: Record<StrategyGate['status'], string> = {
  PASS: 'text-risk-green',
  FAIL: 'text-risk-red',
  ABSENT: 'text-absent',
  MANUAL: 'text-term-faint',
}
const GATE_MARK: Record<StrategyGate['status'], string> = {
  PASS: '✓', FAIL: '⛔', ABSENT: '∅', MANUAL: '✎',
}

function StrategyCard({ strategy, icon: Icon }: { strategy: ExecutionStrategy; icon: typeof Crosshair }) {
  return (
    <div className="border border-term-border bg-term-panel2">
      <div className={cn('flex items-center justify-between gap-2 border-b px-1.5 py-0.5',
        strategy.eligible ? 'border-risk-green/40 bg-risk-green/5' : 'border-term-border')}>
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <Icon size={11} className="shrink-0 text-sony" aria-hidden />
          <span className="truncate text-xxs font-bold uppercase tracking-wide text-sony"
            title={`${strategy.label} — ${strategy.version} · ${strategy.reference}`}>
            {strategy.label}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {strategy.eligible && strategy.sizing_pct !== null && (
            <span className="text-xxs font-bold tabular-nums text-term-text"
              title="Taille autorisée (palier VIX × modificateur session), en % de la calibration">
              {strategy.sizing_pct} %
            </span>
          )}
          <Badge variant={strategy.eligible ? 'green' : 'red'}>
            {strategy.eligible ? 'ÉLIGIBLE' : 'BLOQUÉE'}
          </Badge>
        </span>
      </div>
      <div className="flex items-baseline justify-between gap-2 px-1.5 pt-0.5 text-xxs text-term-dim">
        <span>{strategy.window}</span>
        <span className="truncate" title={strategy.score_threshold}>{strategy.score_threshold.split('·')[0]}</span>
      </div>
      <ul className="px-1.5 pb-1 pt-0.5">
        {strategy.gates.map((gate) => (
          <li key={gate.name} className="flex items-baseline gap-1.5 text-xxs">
            <span className={cn('w-3 shrink-0 text-center font-bold', GATE_STYLE[gate.status])}
              aria-label={gate.status}>{GATE_MARK[gate.status]}</span>
            <span className={cn('shrink-0', GATE_STYLE[gate.status])}>{gate.name}</span>
            <span className="truncate text-term-faint" title={gate.detail}>{gate.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function StrategiesPanel() {
  const strategies = useTerminal((s) => s.s1_state?.strategies ?? null)
  return (
    <Panel code="S1S" title="Stratégies d'exécution — Sony" block="s1_state.strategies" accent="sony">
      {!strategies ? (
        <p className="text-xxs text-term-faint">en attente du flux…</p>
      ) : (
        <div className="space-y-1.5">
          <StrategyCard strategy={strategies.svs} icon={Crosshair} />
          <StrategyCard strategy={strategies.mean_reversion} icon={Magnet} />
          <p className="text-center text-xxs text-term-faint">
            ✎ = source non câblée (responsabilité opérateur) · ∅ = donnée absente (fail-closed) · /reference/sony/
          </p>
        </div>
      )}
    </Panel>
  )
}
