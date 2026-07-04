/** C2 — Streak de pertes → audit forcé à 8 (proximité du seuil VISIBLE).
 *  L'acquittement écrit un ack Redis lié au streak courant : un nouveau streak
 *  redemandera un nouvel audit. */
import { useState } from 'react'
import { Flame } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'

const THRESHOLD = 8

export function StreakPanel() {
  const extras = useTerminal((s) => s.extras)
  const operator = useTerminal((s) => s.operator)
  const [busy, setBusy] = useState(false)
  const streak = extras?.streak ?? 0
  const acked = extras?.streak_acked ?? false
  const atThreshold = streak >= THRESHOLD

  return (
    <Panel code="C2" title="Streak pertes" block="projection OutcomeEvents">
      <div className="flex items-center gap-1" role="img" aria-label={`streak ${streak} sur seuil ${THRESHOLD}`}>
        {Array.from({ length: THRESHOLD }, (_, i) => (
          <span key={i} className={cn('h-3 flex-1 border',
            i < streak
              ? i >= THRESHOLD - 2 ? 'border-risk-red bg-risk-red/60' : 'border-risk-yellow bg-risk-yellow/40'
              : 'border-term-border bg-term-grid')} />
        ))}
      </div>
      <div className="mt-1 flex items-center justify-between">
        <span className="inline-flex items-center gap-1 tabular-nums">
          <Flame size={11} className={atThreshold ? 'text-risk-red' : 'text-term-dim'} aria-hidden />
          <b className={atThreshold ? 'text-risk-red' : undefined}>{streak}</b>
          <span className="text-term-dim">/ {THRESHOLD} → audit forcé</span>
        </span>
        {atThreshold && !acked && (
          <Button variant="nogo" disabled={busy}
            onClick={async () => {
              setBusy(true)
              try { await api.ackAudit(operator) } finally { setBusy(false) }
            }}>
            Acquitter l'audit
          </Button>
        )}
        {atThreshold && acked && <span className="text-xxs text-risk-green">audit acquitté</span>}
      </div>
    </Panel>
  )
}
