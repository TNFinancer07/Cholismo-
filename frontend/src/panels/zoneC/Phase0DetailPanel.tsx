/** C1 — Détail Phase 0 : liste des `phase0_blockers` actifs (+ warnings non bloquants).
 *  Reflet du moteur déterministe — rien ici n'est cliquable pour « débloquer ». */
import { OctagonX, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { useTerminal } from '@/store/terminal'

export function Phase0DetailPanel() {
  const si = useTerminal((s) => s.session_identity)
  const blockers = si?.phase0_blockers ?? []
  const warnings = si?.phase0_warnings ?? []

  return (
    <Panel code="C1" title="Phase 0 — règles" block="session_identity.phase0_blockers">
      {blockers.length === 0 && warnings.length === 0 && (
        <p className="inline-flex items-center gap-1.5 text-risk-green">
          <CheckCircle2 size={12} aria-hidden /> Toutes les règles passent — OUVERT
        </p>
      )}
      <ul className="space-y-0.5">
        {blockers.map((b) => (
          <li key={b.rule} className="flex items-start gap-1.5 border-l-2 border-risk-red bg-risk-red/5 px-1.5 py-0.5">
            <OctagonX size={11} className="mt-0.5 shrink-0 text-risk-red" aria-hidden />
            <div>
              <div className="text-xxs font-bold uppercase text-risk-red">{b.rule} — {b.label}</div>
              {b.detail && <div className="text-xxs text-term-dim">{b.detail}</div>}
            </div>
          </li>
        ))}
        {warnings.map((w) => (
          <li key={w.rule} className="flex items-start gap-1.5 border-l-2 border-risk-yellow bg-risk-yellow/5 px-1.5 py-0.5">
            <AlertTriangle size={11} className="mt-0.5 shrink-0 text-risk-yellow" aria-hidden />
            <div>
              <div className="text-xxs font-bold uppercase text-risk-yellow">{w.rule} — {w.label} (warn)</div>
              {w.detail && <div className="text-xxs text-term-dim">{w.detail}</div>}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}
