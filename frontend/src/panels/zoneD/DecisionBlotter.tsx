/** ZONE D — Decision Log (event-sourced, append-only). Vue = PROJECTION rejouant les
 *  events (DecisionEvent ← OutcomeEvent ← ReconEvent), façon blotter Murex/Calypso :
 *  horodaté, auditable, immuable. Import CSV NinjaTrader → ReconEvents. */
import { useRef, useState } from 'react'
import { FileUp, ShieldQuestion } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { fmtNum, fmtTs } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import type { BlotterRow } from '@/types/schema'

function OutcomeCell({ row }: { row: BlotterRow }) {
  const [busy, setBusy] = useState(false)
  if (row.outcome) {
    const cls = row.outcome.outcome === 'WIN' ? 'text-risk-green'
      : row.outcome.outcome === 'LOSS' ? 'text-risk-red' : 'text-term-dim'
    return (
      <span className={cn('tabular-nums', cls)}>
        {row.outcome.outcome}
        {row.outcome.r_multiple !== null && ` ${fmtNum(row.outcome.r_multiple, 2)}R`}
        {row.outcome.error_type && ` · err ${row.outcome.error_type}`}
      </span>
    )
  }
  if (row.decision !== 'GO') return <span className="text-term-faint">—</span>
  return (
    <span className="inline-flex gap-1">
      {(['WIN', 'LOSS', 'SCRATCH'] as const).map((o) => (
        <button key={o} disabled={busy}
          className="border border-term-border px-1 text-xxs text-term-dim hover:text-term-text"
          title={`Écrire un OutcomeEvent ${o} (event ultérieur référençant la décision)`}
          onClick={async () => {
            setBusy(true)
            try {
              await api.postOutcome({ decision_id: row.id, outcome: o,
                r_multiple: o === 'WIN' ? 1 : o === 'LOSS' ? -1 : 0 })
            } finally { setBusy(false) }
          }}>
          {o[0]}
        </button>
      ))}
    </span>
  )
}

export function DecisionBlotter() {
  const decisions = useTerminal((s) => s.decisions)
  const fileRef = useRef<HTMLInputElement>(null)
  const [importMsg, setImportMsg] = useState<string | null>(null)

  async function onImport(file: File) {
    try {
      const res = await api.reconImport(file, 0) as Record<string, number>
      setImportMsg(`fills:${res.fills_parsed} · matchés:${res.matched} · GO sans fill:${res.go_without_fill} · fills sans GO:${res.fill_without_go}`)
    } catch (err) {
      setImportMsg(`échec import : ${(err as Error).message}`)
    }
  }

  return (
    <Panel code="D" title="Decision Log — event-sourced · append-only" block="events → projection"
      right={
        <div className="flex items-center gap-2">
          {importMsg && <span className="max-w-96 truncate text-xxs text-term-dim">{importMsg}</span>}
          <Button variant="ghost" onClick={() => fileRef.current?.click()}
            title="Import CSV NinjaTrader → réconciliation décision ↔ exécution réelle">
            <FileUp size={11} aria-hidden /> Import NinjaTrader
          </Button>
          <input ref={fileRef} type="file" accept=".csv" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void onImport(f); e.target.value = '' }} />
        </div>
      }>
      <table className="w-full border-collapse text-xxs tabular-nums">
        <thead>
          <tr className="border-b border-term-border text-left uppercase text-term-faint">
            <th className="py-0.5 pr-2 font-semibold">ts</th>
            <th className="pr-2 font-semibold">opérateur</th>
            <th className="pr-2 font-semibold">instr.</th>
            <th className="pr-2 font-semibold">décision</th>
            <th className="pr-2 font-semibold">score</th>
            <th className="pr-2 font-semibold">motif</th>
            <th className="pr-2 font-semibold">self-check</th>
            <th className="pr-2 font-semibold">outcome</th>
            <th className="pr-2 font-semibold">réconciliation</th>
          </tr>
        </thead>
        <tbody>
          {decisions.length === 0 && (
            <tr><td colSpan={9} className="py-2 text-center text-term-faint">
              aucun event — le log est vide (et restera immuable une fois écrit)
            </td></tr>
          )}
          {decisions.map((row) => (
            <tr key={row.id} className="border-b border-term-grid hover:bg-term-panel2">
              <td className="py-0.5 pr-2 text-term-dim">{fmtTs(row.ts)}</td>
              <td className={cn('pr-2', row.operator === 'SONY' ? 'text-sony'
                : row.operator === 'YOUSSEF' ? 'text-youssef' : 'text-term-dim')}>{row.operator}</td>
              <td className="pr-2">{row.instrument ?? '—'}</td>
              <td className="pr-2">
                <Badge variant={row.decision === 'GO' ? 'green' : 'red'}>{row.decision}</Badge>
                {row.degraded && <span className="ml-1 text-risk-yellow" title="signal dégradé /80">◬</span>}
              </td>
              <td className="pr-2">{row.signal_score === null ? '—' : fmtNum(row.signal_score, 1)}</td>
              <td className="pr-2 text-term-dim">{row.reason ?? '—'}</td>
              <td className="pr-2">{row.cognitive_selfcheck ? '✓' : row.decision === 'GO' ? '?' : '—'}</td>
              <td className="pr-2"><OutcomeCell row={row} /></td>
              <td className="pr-2">
                {row.recon === null
                  ? <span className="inline-flex items-center gap-1 text-term-faint"><ShieldQuestion size={10} aria-hidden />non réconcilié</span>
                  : row.recon.matched
                    ? <Badge variant="green">MATCHÉ</Badge>
                    : <Badge variant="red" title="GO sans fill correspondant — anomalie comportementale">NON MATCHÉ</Badge>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}
