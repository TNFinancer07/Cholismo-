/** B2 — Bridge Variables (`bridge_variables`). GEX affiché avec l'ÂGE RÉEL de la donnée
 *  (now − gex_last_compute_ts) — pas de faux countdown (PRD §B2) : le TTL du moteur
 *  Greeks est inconnu. STALE au-delà du seuil unique GEX_STALE_SECONDS. */
import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { MetaValue, useDataAge } from '@/components/MetaValue'
import { Sparkline } from '@/components/Sparkline'
import { fmtAge, fmtGex, fmtNum } from '@/lib/format'
import { useTerminal } from '@/store/terminal'
import { cn } from '@/lib/utils'

export function BridgePanel() {
  const bridge = useTerminal((s) => s.bridge_variables)
  const gexAge = useDataAge(bridge?.gex)
  const gexStale = bridge?.gex.freshness === 'STALE'
  const gexAbsent = !bridge || bridge.gex.freshness === 'ABSENT'

  return (
    <Panel code="B2" title="Bridge Variables" block="bridge_variables" owner="S1 + S2">
      <div className="flex items-baseline justify-between gap-2 border-b border-term-grid pb-1">
        <span className="text-xxs uppercase text-term-dim">GEX</span>
        <span className="flex items-baseline gap-2 tabular-nums">
          <Sparkline seriesKey="gex" width={56} height={12} stroke="auto" />
          <MetaValue meta={bridge?.gex} render={(v) => fmtGex(v as number)} className="text-sm" />
        </span>
      </div>
      <div className="flex items-center justify-between py-1 text-xxs">
        <span className="uppercase text-term-dim" title="Âge réel = now − gex_last_compute_ts. Le moteur Greeks recalcule à sa propre vitesse, inconnue.">
          âge de donnée (réel)
        </span>
        <span className={cn('inline-flex items-center gap-1.5 tabular-nums',
          gexAbsent ? 'text-absent' : gexStale ? 'text-risk-yellow' : 'text-term-text')}>
          {gexAge === null ? '—' : fmtAge(gexAge)}
          {gexStale && <Badge variant="yellow">STALE</Badge>}
          {gexAbsent && <Badge variant="red">ABSENT</Badge>}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 border-t border-term-grid pt-1">
        <div className="flex items-baseline justify-between">
          <span className="text-xxs uppercase text-term-dim">VVIX</span>
          <MetaValue meta={bridge?.vvix} render={(v) => fmtNum(v as number, 1)} />
        </div>
        <div className="flex items-baseline justify-between">
          <span className="text-xxs uppercase text-term-dim">DXY</span>
          <MetaValue meta={bridge?.dxy} render={(v) => fmtNum(v as number, 3)} />
        </div>
      </div>
    </Panel>
  )
}
