/** SENT — positionnement Long/Short agrégé (bloc `long_short_ratio`, D-053, canal lent).
 *
 *  ⚠ Nommage : dans ce terminal « LSR » désigne le moteur **Liquidity Sweep Reversal**
 *  (`lsr_engine`, `lsr_driver`, logs « LSR manifest émis »). Ce panneau montre le **Long/Short
 *  Ratio** d'une venue de positionnement — deux choses sans rapport. Le fichier garde le nom
 *  demandé, mais le mnémonique opérateur est **SENT** : surcharger « LSR » en séance serait un
 *  piège de lecture.
 *
 *  Le panneau MONTRE, il ne conclut pas (§2.1) : aucune lecture contrarienne, aucun signal
 *  dérivé. La jauge est la donnée elle-même. §3 : la couleur n'est jamais seule — libellés
 *  LONG/SHORT, position (long à gauche, short à droite), flèches ▲/▼ et badges texte.
 */
import { AlertTriangle, Unplug } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { FlagIcons, useDataAge } from '@/components/MetaValue'
import { fmtAge, fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'
import type { LongShortInstrument } from '@/types/schema'

function Delta({ value }: { value: number | null }) {
  if (value === null) {
    return <span className="text-term-faint" title="variation 24 h indisponible">—</span>
  }
  const up = value > 0
  const flat = value === 0
  return (
    <span className={cn('tabular-nums', flat ? 'text-term-dim' : up ? 'text-risk-green' : 'text-risk-red')}
      title="variation du positionnement long sur 24 h">
      {flat ? '=' : up ? '▲' : '▼'} {fmtNum(Math.abs(value), 1)} pt
    </span>
  )
}

function Row({ inst }: { inst: LongShortInstrument }) {
  const longSide = Math.max(0, Math.min(100, inst.long_pct))
  return (
    <li className="border-b border-term-border/50 py-1 last:border-b-0" data-testid={`ls-row-${inst.symbol}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="flex items-baseline gap-1.5">
          <span className="text-xxs font-bold uppercase tracking-wide text-term-text">{inst.symbol}</span>
          {inst.imbalanced && (
            <span className="inline-flex items-center gap-0.5 rounded-sm border border-risk-yellow px-1 text-xxs font-bold text-risk-yellow"
              data-testid={`ls-imbalance-${inst.symbol}`}
              title="Positionnement concentré d'un côté — fait observé, aucune conclusion tirée">
              <AlertTriangle size={9} aria-hidden /> DÉSÉQUILIBRE
            </span>
          )}
        </span>
        <span className="flex items-baseline gap-2 text-xxs">
          <span className="text-term-dim">
            ratio{' '}
            <span className="font-bold tabular-nums text-term-text" data-testid={`ls-ratio-${inst.symbol}`}>
              {inst.ratio === null ? 'N/D' : fmtNum(inst.ratio, 2)}
            </span>
          </span>
          <Delta value={inst.delta_24h_pct} />
        </span>
      </div>
      {/* Jauge : LONG à gauche, SHORT à droite. Les deux libellés sont TOUJOURS écrits —
          la lecture ne dépend jamais de la seule couleur (§3). */}
      <div className="mt-0.5 flex h-3.5 w-full overflow-hidden rounded-sm border border-term-border"
        role="img"
        aria-label={`${inst.symbol} : ${fmtNum(inst.long_pct, 1)} % long, ${fmtNum(inst.short_pct, 1)} % short`}>
        <div className="flex items-center justify-start bg-risk-green/25 px-1"
          style={{ width: `${longSide}%` }} data-testid={`ls-bar-long-${inst.symbol}`}>
          <span className="whitespace-nowrap text-xxs font-bold tabular-nums text-risk-green">
            {fmtNum(inst.long_pct, 1)}
          </span>
        </div>
        <div className="flex flex-1 items-center justify-end bg-risk-red/25 px-1"
          data-testid={`ls-bar-short-${inst.symbol}`}>
          <span className="whitespace-nowrap text-xxs font-bold tabular-nums text-risk-red">
            {fmtNum(inst.short_pct, 1)}
          </span>
        </div>
      </div>
      <div className="flex justify-between text-xxs uppercase tracking-wide text-term-faint">
        <span>long</span>
        <span>{inst.accounts === null ? '' : `${inst.accounts.toLocaleString('fr-FR')} comptes`}</span>
        <span>short</span>
      </div>
    </li>
  )
}

export function LsrSentimentPanel() {
  const meta = useTerminal((s) => s.long_short_ratio)
  const age = useDataAge(meta)
  const value = meta && meta.freshness !== 'ABSENT' ? meta.value : null

  return (
    <Panel code="SENT" title="Positionnement Long/Short" block="long_short_ratio" accent="youssef"
      right={value ? <span className="text-xxs text-term-faint">{value.venue}</span> : undefined}>
      {!value || value.instruments.length === 0 ? (
        // Fail-closed (§3) : aucune jauge à moitié inventée, un message franc.
        <div className="flex h-full flex-col items-center justify-center gap-1 text-absent absent-pulse"
          data-testid="ls-offline">
          <Unplug size={14} aria-hidden />
          <span className="text-xxs font-bold tracking-tight">PAS DE DONNÉES</span>
          <span className="text-xxs text-term-faint">flux de positionnement absent</span>
        </div>
      ) : (
        <>
          {meta?.freshness === 'STALE' && (
            <div className="mb-1 flex items-center gap-1 border border-stale/50 px-1 py-0.5 text-xxs text-stale"
              data-testid="ls-stale">
              PÉRIMÉ {fmtAge(age)} — positionnement figé <FlagIcons meta={meta} />
            </div>
          )}
          <ul className={cn(meta?.freshness === 'STALE' && 'opacity-60')}>
            {value.instruments.map((inst) => <Row key={inst.symbol} inst={inst} />)}
          </ul>
          <div className="mt-1 flex justify-between text-xxs text-term-faint">
            <span>déséquilibre ≥ {fmtNum(value.extreme_pct, 0)} %</span>
            {value.dropped > 0 && (
              // Une ligne écartée par le moteur se VOIT : silence = donnée perdue sans trace.
              <span className="text-risk-yellow" data-testid="ls-dropped"
                title="Lignes écartées : somme ≠ 100 %, doublon, ou symbole vide">
                {value.dropped} ligne{value.dropped > 1 ? 's' : ''} écartée{value.dropped > 1 ? 's' : ''}
              </span>
            )}
          </div>
        </>
      )}
    </Panel>
  )
}
