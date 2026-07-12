/** OB — carnet d'ordres ES (DOM 10 niveaux) lisant UN champ : `s1_state.order_book`
 *  (D-025). Lecture seule ABSOLUE (§2.1) : aucun clic ne fait rien — contrairement aux
 *  DOM d'exécution, ce panneau n'a AUCUN chemin d'ordre. Fail-closed honnête : STALE =
 *  grisé + âge réel ; ABSENT = « PAS DE DONNÉES » ; carnet croisé = flag visible.
 *  Côtés BID/ASK libellés en texte — la couleur n'est jamais seule (CLAUDE §3). */
import { useMemo } from 'react'
import { cn } from '@/lib/utils'
import { fmtAge, fmtInt, fmtNum } from '@/lib/format'
import { useTerminal } from '@/store/terminal'
import { FlagIcons, useDataAge } from '@/components/MetaValue'
import { Panel } from '@/components/ui/panel'
import type { OrderBookValue } from '@/types/schema'

const BAR_MAX_PCT = 92 // la barre ne mange jamais tout le rang — le chiffre reste lisible

function Ladder({ book }: { book: OrderBookValue }) {
  const { maxSize, bidTotal, askTotal } = useMemo(() => {
    const sizes = [...book.bids, ...book.asks].map(([, size]) => size)
    return {
      maxSize: Math.max(1, ...sizes),
      bidTotal: book.bids.reduce((acc, [, s]) => acc + s, 0),
      askTotal: book.asks.reduce((acc, [, s]) => acc + s, 0),
    }
  }, [book])

  const bestBid = book.bids[0]?.[0]
  const bestAsk = book.asks[0]?.[0]
  const spread = bestBid !== undefined && bestAsk !== undefined ? bestAsk - bestBid : null
  // Imbalance Σbid/(Σbid+Σask) — dérivation PURE d'affichage du même champ (rien d'inventé).
  const imbalancePct = (100 * bidTotal) / Math.max(1, bidTotal + askTotal)

  const row = (price: number, size: number, side: 'bid' | 'ask') => (
    <div key={`${side}-${price}`} className="relative grid h-[15px] grid-cols-[1fr_64px_1fr] items-center font-mono text-xxs tabular-nums">
      <div aria-hidden className={cn('absolute inset-y-[1px]',
        side === 'bid' ? 'right-[calc(50%+32px)] bg-risk-green/15' : 'left-[calc(50%+32px)] bg-risk-red/15')}
        style={{ width: `${(BAR_MAX_PCT * size) / maxSize / 2}%` }} />
      <span className={cn('relative pr-1 text-right', side === 'bid' ? 'text-term-text' : 'text-term-faint')}>
        {side === 'bid' ? fmtInt(size) : ''}
      </span>
      <span className={cn('relative text-center', side === 'bid' ? 'text-risk-green' : 'text-risk-red')}>
        {fmtNum(price, 2)}
      </span>
      <span className={cn('relative pl-1', side === 'ask' ? 'text-term-text' : 'text-term-faint')}>
        {side === 'ask' ? fmtInt(size) : ''}
      </span>
    </div>
  )

  return (
    <div className="flex flex-col">
      <div className="grid grid-cols-[1fr_64px_1fr] pb-0.5 text-center font-mono text-xxs uppercase text-term-faint">
        <span className="pr-1 text-right text-risk-green">taille bid</span>
        <span>prix</span>
        <span className="pl-1 text-left text-risk-red">taille ask</span>
      </div>
      {[...book.asks].reverse().map(([price, size]) => row(price, size, 'ask'))}
      <div className="my-0.5 grid grid-cols-[1fr_64px_1fr] items-center border-y border-dashed border-term-grid py-0.5 text-center font-mono text-xxs">
        <span className="pr-1 text-right text-term-faint">spread</span>
        <span className="font-bold text-term-text">{spread === null ? '—' : fmtNum(spread, 2)}</span>
        <span className="pl-1 text-left text-term-faint">{spread === null ? '' : `${Math.round(spread / 0.25)} tick(s)`}</span>
      </div>
      {book.bids.map(([price, size]) => row(price, size, 'bid'))}
      <div className="mt-1 border-t border-term-border pt-1">
        <div className="flex items-center justify-between font-mono text-xxs text-term-faint">
          <span>imbalance Σbid {fmtNum(imbalancePct, 0)} %</span>
          <span>Σbid {fmtInt(bidTotal)} · Σask {fmtInt(askTotal)}</span>
        </div>
        <div className="mt-0.5 flex h-1.5 w-full overflow-hidden border border-term-border"
          role="img" aria-label={`imbalance bid ${Math.round(imbalancePct)} %`}>
          <div className="bg-risk-green/60" style={{ width: `${imbalancePct}%` }} />
          <div className="flex-1 bg-risk-red/40" />
        </div>
      </div>
    </div>
  )
}

export function OrderBookPanel() {
  const meta = useTerminal((s) => s.s1_state?.order_book)
  // Micro-coupure du CANAL SSE (≠ coupure de source) : le dernier payload garde un
  // freshness FRESH figé — sans ce garde, le carnet aurait l'air vivant pendant un
  // mute. L'UI ne laisse jamais une image fraîche mentir (§2.2/§3, /devil).
  const channelMute = useTerminal((s) =>
    s.lastFastEventAt === 0 || s.nowTick - s.lastFastEventAt > 5)
  const age = useDataAge(meta)
  const degraded = meta?.freshness === 'STALE' || channelMute

  return (
    <Panel code="OB" title="Carnet d'ordres ES" block="s1_state.order_book" accent="sony"
      right={meta ? <FlagIcons meta={meta} /> : undefined}>
      {!meta || meta.freshness === 'ABSENT' || !meta.value ? (
        <div className="grid h-full min-h-16 place-items-center">
          <span className="absent-pulse font-mono text-xs font-bold text-absent">PAS DE DONNÉES</span>
        </div>
      ) : (
        <div className={cn(degraded && 'opacity-60')}>
          {channelMute ? (
            <p className="mb-1 border border-absent/60 px-1 py-0.5 text-center font-mono text-xxs uppercase text-absent">
              flux muet — dernière image {fmtAge(age)}
            </p>
          ) : meta.freshness === 'STALE' && (
            <p className="mb-1 border border-stale/50 px-1 py-0.5 text-center font-mono text-xxs uppercase text-stale">
              carnet périmé {fmtAge(age)} — dernière image connue
            </p>
          )}
          <Ladder book={meta.value} />
          <p className="mt-1 text-xxs text-term-faint">
            lecture seule — aucun chemin d'exécution (§2.1) · source : {meta.source || '—'}
          </p>
        </div>
      )}
    </Panel>
  )
}
