/** TP — Tape / Time & Sales lisant UN champ : `s1_state.tape` (D-026). Prints OBSERVÉS
 *  du marché — PAS les ordres de l'opérateur, aucun chemin d'exécution (§2.1). Sens
 *  agresseur : BUY (à l'offre) vert / SELL (au bid) rouge, MAIS jamais la couleur seule —
 *  glyphe ▲/▼ + colonne dédiée + liseré gauche positionnel (§3). Ergonomie rafales (Loop 5) :
 *  heure affichée une fois par seconde + séparateur de groupe ; gros volume (≥ p90) gras +
 *  teinté. Fail-closed honnête : STALE = grisé + âge ; ABSENT = « PAS DE DONNÉES » ; flux
 *  muet signalé. Le plus récent en tête. */
import { cn } from '@/lib/utils'
import { fmtAge, fmtInt, fmtNum } from '@/lib/format'
import { useTerminal } from '@/store/terminal'
import { FlagIcons, useDataAge } from '@/components/MetaValue'
import { Panel } from '@/components/ui/panel'
import type { TapePrint } from '@/types/schema'

function fmtClock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('en-GB', { hour12: false })
}

function Row({ p, big, showTime, groupTop }:
  { p: TapePrint; big: boolean; showTime: boolean; groupTop: boolean }) {
  const buy = p.side === 'BUY'
  return (
    <div
      className={cn(
        // Liseré gauche coloré = repère directionnel POSITIONNEL (jamais la couleur seule,
        // §3) ; l'œil suit les séries d'achats/ventes dans les rafales. border-l-2 + pl-1
        // reproduits sur l'en-tête → colonnes strictement alignées.
        'grid h-[14px] grid-cols-[58px_1fr_46px_22px] items-center gap-x-1.5 border-l-2 pl-1 font-mono text-xxs tabular-nums',
        buy ? 'border-l-risk-green' : 'border-l-risk-red',
        big && 'bg-term-panel2',
        groupTop && 'border-t border-t-term-border/40',   // sépare les groupes de seconde (rafales lisibles)
      )}
      title={big ? 'gros volume — ≥ 90e centile de la fenêtre' : undefined}
    >
      {/* Heure affichée une SEULE fois par seconde : rafales sans répétition, structure temporelle claire. */}
      <span className="text-term-faint">{showTime ? fmtClock(p.ts) : ''}</span>
      <span className={cn('pr-2 text-right', buy ? 'text-risk-green' : 'text-risk-red')}>
        {fmtNum(p.price, 2)}
      </span>
      {/* Gros volume : chiffre gras + teinté côté agresseur → « gros achat/vente » saute aux yeux. */}
      <span className={cn('text-right',
        big ? cn('font-bold', buy ? 'text-risk-green' : 'text-risk-red') : 'text-term-text')}>
        {fmtInt(p.size)}
      </span>
      {/* Sens jamais par la couleur seule : glyphe directionnel + colonne dédiée (§3). */}
      <span className={cn('text-center', buy ? 'text-risk-green' : 'text-risk-red')}
        aria-label={buy ? 'acheteur agresseur' : 'vendeur agresseur'}>
        {buy ? '▲' : '▼'}
      </span>
    </div>
  )
}

export function TapePanel() {
  const meta = useTerminal((s) => s.s1_state?.tape)
  const channelMute = useTerminal((s) =>
    s.lastFastEventAt === 0 || s.nowTick - s.lastFastEventAt > 5)
  const age = useDataAge(meta)
  const degraded = meta?.freshness === 'STALE' || channelMute
  const prints = meta?.value ?? []
  // Seuil "gros print" : 90e centile de la fenêtre courante — pure dérivation d'affichage.
  const bigThreshold = prints.length
    ? [...prints].map((p) => p.size).sort((a, b) => a - b)[Math.floor(prints.length * 0.9)]
    : Infinity

  return (
    <Panel code="TP" title="Tape · Time & Sales" block="s1_state.tape" accent="sony"
      right={meta ? <FlagIcons meta={meta} /> : undefined}>
      {!meta || meta.freshness === 'ABSENT' || !meta.value ? (
        <div className="grid h-full min-h-16 place-items-center">
          <span className="absent-pulse font-mono text-xs font-bold text-absent">PAS DE DONNÉES</span>
        </div>
      ) : (
        <div className={cn('flex min-h-0 flex-col', degraded && 'opacity-60')}>
          {channelMute ? (
            <p className="mb-1 border border-absent/60 px-1 py-0.5 text-center font-mono text-xxs uppercase text-absent">
              flux muet — dernière image {fmtAge(age)}
            </p>
          ) : meta.freshness === 'STALE' && (
            <p className="mb-1 border border-stale/50 px-1 py-0.5 text-center font-mono text-xxs uppercase text-stale">
              tape périmé {fmtAge(age)} — dernière image connue
            </p>
          )}
          <div className="grid grid-cols-[58px_1fr_46px_22px] gap-x-1.5 border-l-2 border-l-transparent pb-0.5 pl-1 font-mono text-xxs uppercase text-term-faint">
            <span>heure</span><span className="pr-2 text-right">prix</span>
            <span className="text-right">taille</span><span className="text-center">sens</span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {prints.map((p, i) => {
              // Nouvelle seconde (liste plus-récent-en-tête) → afficher l'heure + séparer le groupe.
              const newSecond = i === 0 || Math.floor(prints[i - 1].ts) !== Math.floor(p.ts)
              return <Row key={p.seq} p={p} big={p.size >= bigThreshold}
                showTime={newSecond} groupTop={i > 0 && newSecond} />
            })}
          </div>
          <p className="mt-1 border-t border-term-border pt-1 text-xxs text-term-faint">
            prints observés — pas les ordres de l'opérateur, aucun chemin d'exécution (§2.1)
          </p>
        </div>
      )}
    </Panel>
  )
}
