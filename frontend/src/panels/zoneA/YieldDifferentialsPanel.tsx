/** YLD — courbe des taux et différentiels (bloc `yield_curve`, D-053, canal lent).
 *
 *  Les spreads affichés ici sont DÉRIVÉS des ténors juste au-dessus (source unique côté backend) :
 *  impossible qu'un différentiel contredise les taux de la même vue. Un ténor manquant fait
 *  disparaître les spreads qui en dépendent — jamais un chiffre calculé sur un trou (§3).
 *
 *  §3 : la couleur n'est jamais seule — signe explicite (+/−), flèches ▲/▼, badge texte
 *  « INVERSÉE », unités écrites (% pour les taux, bp pour les écarts).
 */
import { Unplug } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { FlagIcons, useDataAge } from '@/components/MetaValue'
import { fmtAge, fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import type { YieldSpread, YieldTenor } from '@/types/schema'

/** Variation en points de base — l'absence de mesure reste un tiret, jamais un 0 (0 bp veut
 *  dire « inchangé », ce qui est une information différente). */
function ChangeBp({ value }: { value: number | null }) {
  if (value === null) return <span className="text-term-faint" title="variation indisponible">—</span>
  const up = value > 0
  const flat = value === 0
  return (
    <span className={cn('tabular-nums', flat ? 'text-term-dim' : up ? 'text-risk-green' : 'text-risk-red')}>
      {flat ? '=' : up ? '▲' : '▼'} {fmtNum(Math.abs(value), 1)} bp
    </span>
  )
}

function TenorRow({ tenor }: { tenor: YieldTenor }) {
  return (
    <li className="flex items-baseline justify-between gap-2 px-1 py-0.5 odd:bg-term-panel2"
      data-testid={`yld-tenor-${tenor.code}`}>
      <span className="flex items-baseline gap-1.5">
        <span className="text-xxs font-bold text-term-text">{tenor.code}</span>
        <span className="text-xxs text-term-faint">{tenor.label}</span>
      </span>
      <span className="flex items-baseline gap-2 text-xxs">
        <span className="font-bold tabular-nums text-term-text">
          {fmtNum(tenor.value_pct, 3)} <span className="text-term-dim">%</span>
        </span>
        <ChangeBp value={tenor.change_bp} />
      </span>
    </li>
  )
}

function SpreadRow({ spread }: { spread: YieldSpread }) {
  const positive = spread.value_bp >= 0
  return (
    <div className={cn('flex items-baseline justify-between gap-2 border-l-2 px-1.5 py-1',
      spread.inverted === true ? 'border-risk-red bg-risk-red/10' : 'border-youssef/60 bg-term-panel2')}
      data-testid={`yld-spread-${spread.code}`}>
      <span className="flex items-baseline gap-1.5">
        <span className="text-xxs font-bold uppercase tracking-wide text-term-text">{spread.label}</span>
        {spread.inverted === true && (
          <span className="rounded-sm border border-risk-red px-1 text-xxs font-black text-risk-red"
            data-testid={`yld-inverted-${spread.code}`}
            title="Pente négative : le court rend plus que le long. Fait observé, aucune conclusion tirée.">
            INVERSÉE
          </span>
        )}
      </span>
      <span className="font-mono text-sm font-black tabular-nums text-term-text">
        {positive ? '+' : '−'}{fmtNum(Math.abs(spread.value_bp), 1)}
        <span className="ml-0.5 text-xxs font-normal text-term-dim">bp</span>
      </span>
    </div>
  )
}

export function YieldDifferentialsPanel() {
  const meta = useTerminal((s) => s.yield_curve)
  const age = useDataAge(meta)
  const value = meta && meta.freshness !== 'ABSENT' ? meta.value : null

  if (!value || value.tenors.length === 0) {
    return (
      <Panel code="YLD" title="Taux & différentiels" block="yield_curve" accent="youssef">
        <div className="flex h-full flex-col items-center justify-center gap-1 text-absent absent-pulse"
          data-testid="yld-offline">
          <Unplug size={14} aria-hidden />
          <span className="text-xxs font-bold tracking-tight">PAS DE DONNÉES</span>
          <span className="text-xxs text-term-faint">flux de taux absent</span>
        </div>
      </Panel>
    )
  }

  return (
    <Panel code="YLD" title="Taux & différentiels" block="yield_curve" accent="youssef">
      {meta?.freshness === 'STALE' && (
        <div className="mb-1 flex items-center gap-1 border border-stale/50 px-1 py-0.5 text-xxs text-stale"
          data-testid="yld-stale">
          PÉRIMÉ {fmtAge(age)} — courbe figée <FlagIcons meta={meta} />
        </div>
      )}
      <div className={cn(meta?.freshness === 'STALE' && 'opacity-60')}>
        {/* Différentiels EN EXERGUE : c'est la lecture opérationnelle (pente + driver EUR/USD). */}
        <div className="mb-1.5 space-y-0.5">
          {value.spreads.length === 0 ? (
            <div className="border border-dashed border-term-border px-1.5 py-1 text-xxs text-absent"
              data-testid="yld-no-spread">
              AUCUN DIFFÉRENTIEL CALCULABLE — patte de courbe manquante
            </div>
          ) : (
            value.spreads.map((spread) => <SpreadRow key={spread.code} spread={spread} />)
          )}
        </div>
        <ul>
          {value.tenors.map((tenor) => <TenorRow key={tenor.code} tenor={tenor} />)}
        </ul>
      </div>
    </Panel>
  )
}
