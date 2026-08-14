/** Console orchestrateur (PRD §Console, Étape 7) — 6 sources → risque + action,
 *  arbitrage DÉTERMINISTE côté backend, payload JSON temps réel affiché tel quel.
 *  Statuts VERT/JAUNE/ROUGE toujours doublés d'une forme (RiskGlyph). */
import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { RiskGlyph } from '@/components/RiskGlyph'
import { useTerminal } from '@/store/terminal'
import { cn } from '@/lib/utils'

const ACTION_LABEL: Record<string, string> = {
  NONE: 'aucune action',
  REQUEST_ACK: 'REQUEST_ACK — ack humain requis',
  BLOCK_ENTRY: 'BLOCK_ENTRY — entrée bloquée',
  SUSPEND_TRADING: 'SUSPEND_TRADING',
}

export function OrchestratorConsole() {
  const payload = useTerminal((s) => s.orchestrator)

  return (
    <div className="grid h-full grid-cols-2 gap-1.5 p-1.5">
      <Panel code="ORCH" title="Console orchestrateur — 6 sources" block="arbitrage déterministe">
        <div className="space-y-1">
          {payload && Object.entries(payload.sources).map(([name, src]) => (
            <div key={name} className={cn('flex items-center justify-between border-l-2 bg-term-panel2 px-2 py-1',
              src.level === 'ROUGE' ? 'border-risk-red' : src.level === 'JAUNE' ? 'border-risk-yellow' : 'border-risk-green')}>
              <span className={cn('w-16 font-bold uppercase',
                name === 'SVS' || name === 'S1' ? 'text-sony' : name === 'Youssef' ? 'text-youssef' : 'text-term-text')}>
                {name}
              </span>
              <span className="flex-1 truncate px-2 text-xxs text-term-dim">{src.detail}</span>
              <RiskGlyph level={src.level} />
            </div>
          ))}
        </div>
        <div className="mt-2 border-t border-term-border pt-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xxs uppercase text-term-dim">niveau global</span>
            {payload && <RiskGlyph level={payload.risk_level} size={16} />}
          </div>
          <div className="mt-1 flex items-center justify-between">
            <span className="text-xxs uppercase text-term-dim">action</span>
            <Badge variant={payload?.action === 'NONE' ? 'green' : 'red'}>
              {ACTION_LABEL[payload?.action ?? 'NONE']}
            </Badge>
          </div>
          {payload?.requires_human_ack && (
            <p className="mt-1 border border-risk-red/50 bg-risk-red/10 px-1.5 py-0.5 text-xxs text-risk-red">
              Aucun trade sans ack humain explicite — fail-closed (CLAUDE §2.4)
            </p>
          )}
        </div>
      </Panel>
      <Panel code="JSON" title="Payload temps réel" block="GET /orchestrator">
        <pre className="h-full overflow-auto text-xxs text-term-dim">
          {JSON.stringify(payload, null, 2)}
        </pre>
      </Panel>
    </div>
  )
}
