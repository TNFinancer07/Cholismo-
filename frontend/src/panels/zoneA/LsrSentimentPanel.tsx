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
import { useSlowChannelPending } from '@/lib/channel'
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
  // Géométrie EXACTE : les deux largeurs viennent de la donnée, et rien n'est écrit DANS les
  // bandes. /devil : les pourcentages étaient placés à l'intérieur, et leur largeur minimale
  // déformait la jauge — mesuré à 93,7 % de long pour une donnée à 100 % (une bande de 0 %
  // occupait 6,3 % de la largeur). Une jauge quantitative qui ment sur l'extrême ment là où
  // elle sert. Les chiffres vivent maintenant À CÔTÉ : §3 préservé, géométrie honnête.
  const longSide = Math.max(0, Math.min(100, inst.long_pct))
  const shortSide = Math.max(0, Math.min(100, 100 - longSide))
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
            <span className="font-bold tabular-nums text-term-text" data-testid={`ls-ratio-${inst.symbol}`}
              title={inst.ratio === null
                ? 'Ratio indéterminable : plus personne n’est short'
                : 'Comptes longs / comptes shorts'}>
              {inst.ratio === null ? '—' : fmtNum(inst.ratio, 2)}
            </span>
          </span>
          <Delta value={inst.delta_24h_pct} />
        </span>
      </div>
      {/* Chiffres HORS de la jauge : toujours lisibles quelle que soit la géométrie (§3), et
          la jauge reste une mesure exacte. LONG à gauche, SHORT à droite (position + libellé). */}
      <div className="mt-0.5 flex items-center gap-1.5">
        <span className="w-16 shrink-0 whitespace-nowrap text-xxs font-bold tabular-nums text-risk-green"
          data-testid={`ls-pct-long-${inst.symbol}`}>
          LONG {fmtNum(inst.long_pct, 1)}
        </span>
        <div className="flex h-3 min-w-0 flex-1 overflow-hidden rounded-sm border border-term-border"
          role="img"
          aria-label={`${inst.symbol} : ${fmtNum(inst.long_pct, 1)} % long, ${fmtNum(inst.short_pct, 1)} % short`}>
          <div className="bg-risk-green/40" style={{ width: `${longSide}%` }}
            data-testid={`ls-bar-long-${inst.symbol}`} />
          <div className="bg-risk-red/40" style={{ width: `${shortSide}%` }}
            data-testid={`ls-bar-short-${inst.symbol}`} />
        </div>
        <span className="w-16 shrink-0 whitespace-nowrap text-right text-xxs font-bold tabular-nums text-risk-red"
          data-testid={`ls-pct-short-${inst.symbol}`}>
          {fmtNum(inst.short_pct, 1)} SHORT
        </span>
      </div>
      {inst.accounts !== null && (
        <div className="text-right text-xxs text-term-faint">
          {inst.accounts.toLocaleString('fr-FR')} comptes
        </div>
      )}
    </li>
  )
}

export function LsrSentimentPanel() {
  const meta = useTerminal((s) => s.long_short_ratio)
  const age = useDataAge(meta)
  const value = meta && meta.freshness !== 'ABSENT' ? meta.value : null
  // Canal lent = 15 s : à l'ouverture, « PAS DE DONNÉES » serait exact mais indiscernable d'un
  // flux mort. On dit ce qu'il en est — attendre n'est pas déboguer.
  const pending = useSlowChannelPending()

  return (
    <Panel code="SENT" title="Positionnement Long/Short" block="long_short_ratio" accent="youssef"
      right={(
        // Pedigree TOUJOURS visible (/devil) : la venue permet de trancher une donnée douteuse,
        // et les drapeaux de pathologie (retard, désync) n'apparaissaient qu'en STALE — un bloc
        // FRESH mais horodaté de travers avait donc l'air impeccable.
        <span className="flex items-center gap-1">
          {meta && <FlagIcons meta={meta} />}
          {value && <span className="text-xxs text-term-faint" data-testid="ls-venue">{value.venue}</span>}
        </span>
      )}>
      {!value || value.instruments.length === 0 ? (
        // Fail-closed (§3) : aucune jauge à moitié inventée, un message franc.
        <div className="flex h-full flex-col items-center justify-center gap-1 text-absent absent-pulse"
          data-testid="ls-offline">
          <Unplug size={14} aria-hidden />
          <span className="text-xxs font-bold tracking-tight">
            {pending ? 'EN ATTENTE DU CANAL LENT' : 'PAS DE DONNÉES'}
          </span>
          <span className="text-xxs text-term-faint">
            {pending ? 'premier envoi sous 15 s' : 'flux de positionnement absent'}
          </span>
        </div>
      ) : (
        <>
          {meta?.freshness === 'STALE' && (
            <div className="mb-1 border border-stale/50 px-1 py-0.5 text-xxs text-stale"
              data-testid="ls-stale">
              PÉRIMÉ {fmtAge(age)} — positionnement figé
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
