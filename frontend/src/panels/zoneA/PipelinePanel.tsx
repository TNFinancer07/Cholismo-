/** S2P — Le pipeline macro réel de Youssef (`s2_state.pipeline`) — reference/youssef/01-03.
 *  Régime kurtosis VIX (hystérésis + multiplicateurs) → quadrant Bridgewater (poids D1-D5)
 *  → N3 Flux 1 (tanh + gate D4, conviction, 4 horizons) → Flux 2 (6 arbitrages).
 *  Formules AUTORITÉ ; intrants simulés par le mock tant qu'aucun feed réel (MANIFEST). */
import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'

const TIER_STYLE: Record<string, string> = {
  GREEN: 'border-risk-green text-risk-green',
  YELLOW: 'border-risk-yellow text-risk-yellow',
  ORANGE: 'border-orange-400 text-orange-400',
  RED: 'border-risk-red text-risk-red',
}
const HORIZON_LABELS: Record<string, string> = {
  long_4_12_sem: 'LONG 4-12 sem',
  moyen_1_4_sem: 'MOYEN ★ 1-4 sem',
  court_1_5_j: 'COURT 1-5 j',
  intra: 'INTRA (flux)',
}

export function PipelinePanel() {
  const pipeline = useTerminal((s) => s.s2_state?.pipeline ?? null)
  if (!pipeline) {
    return (
      <Panel code="S2P" title="Pipeline macro — Youssef" block="s2_state.pipeline" accent="youssef">
        <p className="text-xxs text-term-faint">en attente du canal lent…</p>
      </Panel>
    )
  }
  const { regime, quadrant, flux1, arbitrages } = pipeline

  return (
    <Panel code="S2P" title="Pipeline macro — Youssef" block="s2_state.pipeline" accent="youssef">
      {/* Phase 0 / D4 — régime kurtosis VIX */}
      <div className="flex items-center justify-between gap-2">
        <span className={cn('border px-1.5 py-0.5 text-xxs font-black tracking-widest',
          TIER_STYLE[regime.tier])}
          title="Régime kurtosis VIX — hystérésis entry/exit 18/14 · 26/22 · 37/33 (reference/youssef/01)">
          D4 · {regime.tier}
        </span>
        <span className="text-xxs tabular-nums text-term-dim">
          carry ×{regime.carry_mult} · fund ×{regime.fund_mult} · score ×{regime.score_mult}
          {regime.kurtosis === null && <span className="text-term-faint" title="kurtosis non câblé"> · kurt ∅</span>}
        </span>
      </div>

      {/* Étape 0 — quadrant Bridgewater + poids D1-D5 */}
      <div className="mt-1.5 border border-term-border bg-term-panel2 p-1.5">
        <div className="flex items-baseline justify-between">
          <span className="text-xxs font-bold uppercase tracking-wider text-youssef">
            Étape 0 · {quadrant.quadrant ?? '—'}
          </span>
          <span className="text-xxs tabular-nums text-term-dim">
            g {fmtSigned(quadrant.g, 2)} · π {fmtSigned(quadrant.pi, 2)} · conf {fmtNum(quadrant.confidence, 2)}
            {' · '}
            <span className={quadrant.transition_risk === 'high' ? 'text-risk-red'
              : quadrant.transition_risk === 'moderate' ? 'text-risk-yellow' : 'text-risk-green'}>
              transition {quadrant.transition_risk}
            </span>
          </span>
        </div>
        <div className="mt-1 flex gap-1" role="img" aria-label="Poids D1-D5 du quadrant">
          {Object.entries(quadrant.weights).map(([dim, weight]) => (
            <div key={dim} className="flex-1 text-center" title={`${dim} — poids ${weight}`}>
              <div className="flex h-6 items-end border border-term-grid bg-term-grid">
                <div className="w-full bg-youssef/50"
                  style={{ height: `${Math.min(100, weight * 240)}%` }} />
              </div>
              <span className="text-xxs text-term-dim">{dim}</span>
              <div className="text-xxs tabular-nums text-term-faint">{fmtNum(flux1.d_scores[dim], 2)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* N3 Flux 1 — score, conviction, horizons */}
      <div className="mt-1.5 flex items-baseline justify-between">
        <span className="text-xxs uppercase text-term-dim">N3 Flux 1 (tanh × gate D4)</span>
        <span className="tabular-nums">
          <b className={cn('text-sm', flux1.direction === 'SHORT' ? 'text-risk-red'
            : flux1.direction === 'LONG' ? 'text-risk-green' : 'text-term-dim')}>
            {flux1.direction} {fmtSigned(flux1.score_final, 3)}
          </b>
          <span className="ml-1 text-xxs text-term-dim">conv {fmtNum(flux1.conviction, 1)}/10</span>
        </span>
      </div>
      <div className="mt-0.5 grid grid-cols-4 gap-1 text-center">
        {Object.entries(flux1.horizons).map(([key, value]) => (
          <div key={key} className={cn('border border-term-grid px-0.5 py-0.5',
            key === 'moyen_1_4_sem' && 'border-youssef/50')}>
            <div className="truncate text-xxs text-term-faint">{HORIZON_LABELS[key] ?? key}</div>
            <div className="text-xxs font-bold tabular-nums">{value === null ? 'flux' : fmtSigned(value, 2)}</div>
          </div>
        ))}
      </div>

      {/* N3 Flux 2 — les 6 arbitrages d'anticipation */}
      <table className="mt-1.5 w-full border-collapse text-xxs tabular-nums">
        <thead>
          <tr className="border-b border-term-border text-left uppercase text-term-faint">
            <th className="py-0.5 font-semibold">arb</th>
            <th className="font-semibold">δ / seuil</th>
            <th className="font-semibold">direction</th>
            <th className="font-semibold">conv</th>
          </tr>
        </thead>
        <tbody>
          {arbitrages.map((arb) => (
            <tr key={arb.arb_id} className={cn('border-b border-term-grid',
              arb.active ? '' : 'opacity-50')}
              title={`${arb.name} (${arb.source_dim} · ${arb.horizon}) — ${arb.threshold} — ${arb.note}`}>
              <td className="py-0.5">
                <span className={cn('font-bold', arb.active ? 'text-youssef' : 'text-term-dim')}>
                  {arb.arb_id} · {arb.name}
                </span>
              </td>
              <td>{arb.delta === null ? '∅' : fmtSigned(arb.delta, 2)}
                <span className="text-term-faint"> / {arb.threshold.replace('|δ| > ', '').replace('|z| > ', 'z').replace('|signal| > ', '').split(' ')[0]}</span>
              </td>
              <td className={arb.direction === 'LONG_BASE' ? 'text-risk-green'
                : arb.direction === 'SHORT_BASE' ? 'text-risk-red' : 'text-term-faint'}>
                {arb.direction ?? (arb.active === null ? 'intrants ∅' : 'inactif')}
              </td>
              <td>{arb.conviction === null ? '—' : fmtNum(arb.conviction, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-center text-xxs text-term-faint">
        formules AUTORITÉ /reference/youssef/ · intrants N1-N2A simulés par le mock (D-021)
      </p>
    </Panel>
  )
}
