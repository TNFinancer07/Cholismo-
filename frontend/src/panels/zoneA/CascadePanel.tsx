/** A1 — Cascade analytique NQ/ES → VIX → ZN → DX → EUR/USD (canal lent, violet).
 *  `real_rates` EN EXERGUE (driver primaire, pivot visuel). Nœud périmé → STALE explicite. */
import { ArrowDown } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { MetaValue } from '@/components/MetaValue'
import { Sparkline } from '@/components/Sparkline'
import { fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import type { MetaField } from '@/types/schema'

const NODES: { key: 'nq_es' | 'vix' | 'zn' | 'dx' | 'eurusd'; label: string; render: (v: unknown) => string }[] = [
  { key: 'nq_es', label: 'NQ/ES', render: (v) => fmtSigned(v as number, 3) },
  { key: 'vix', label: 'VIX', render: (v) => fmtNum(v as number, 2) },
  { key: 'zn', label: 'ZN', render: (v) => fmtSigned(v as number, 3) },
  { key: 'dx', label: 'DX', render: (v) => fmtSigned(v as number, 3) },
  { key: 'eurusd', label: 'EUR/USD', render: (v) => fmtNum(v as number, 5) },
]

function regimeClass(key: string, meta: MetaField | undefined): string {
  if (!meta || meta.value === null) return 'border-term-border'
  const v = Number(meta.value)
  if (key === 'vix') return v > 30 ? 'border-risk-red' : v > 20 ? 'border-risk-yellow' : 'border-risk-green'
  return v > 0 ? 'border-risk-green' : v < 0 ? 'border-risk-red' : 'border-term-border'
}

export function CascadePanel() {
  const s2 = useTerminal((s) => s.s2_state)
  const cascade = s2?.cascade

  return (
    <Panel code="A1" title="Cascade macro" block="s2_state.cascade" accent="youssef">
      {/* real_rates en exergue — pivot visuel */}
      <div className="mb-1.5 border-2 border-youssef bg-youssef/10 px-2 py-1"
        title="Driver primaire de la cascade (PRD §A1)">
        <div className="flex items-baseline justify-between">
          <span className="text-xxs font-bold uppercase tracking-widest text-youssef">★ Taux réels — driver primaire</span>
          <MetaValue meta={cascade?.real_rates} render={(v) => fmtNum(v as number, 2)} unit="%" className="text-base font-black" />
        </div>
      </div>
      <ol className="space-y-0.5">
        {NODES.map((node, i) => {
          const meta = cascade?.[node.key]
          return (
            <li key={node.key}>
              <div className={cn('flex items-baseline justify-between border-l-2 bg-term-panel2 px-1.5 py-0.5',
                regimeClass(node.key, meta))}>
                <span className="flex items-baseline gap-2">
                  <span className="text-xxs font-semibold uppercase text-term-dim">{node.label}</span>
                  {node.key === 'vix' && <Sparkline seriesKey="vix" width={52} height={11} stroke="auto" />}
                </span>
                <MetaValue meta={meta} render={node.render} className="tabular-nums" />
              </div>
              {i < NODES.length - 1 && (
                <div className="flex justify-center text-term-faint"><ArrowDown size={9} aria-hidden /></div>
              )}
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}
