/** EC — Calendrier économique lisant UN champ : `econ_calendar.events` (D-027). Feed
 *  SYSTÉMIQUE (macro/géo) : impacte la liquidité pour LES DEUX opérateurs. Chaque
 *  événement PROGRAMMÉ porte son heure CONNUE → compte à rebours honnête et précis,
 *  dérivé côté client de `serverNow` (contraste B2 : pas de countdown vers une péremption
 *  inconnue, §8.2). Impact liquidité Tier 1/2/3 JAMAIS par la couleur seule : nombre de
 *  carrés pleins (forme) + texte T1/T2/T3 + libellé (§3). Fenêtre news T1 ±30 min
 *  SIGNALÉE (filtre Sony, AUTORITÉ) — factuelle, PAS un verdict Phase 0 (l'UI ne prononce
 *  jamais OUVERT/BLOQUÉ ici, §2.2). Fail-closed : périmé = grisé + âge ; absent = PAS DE
 *  DONNÉES ; jamais un événement inventé. */
import { cn } from '@/lib/utils'
import { fmtAge } from '@/lib/format'
import { serverNow, useTerminal } from '@/store/terminal'
import { FlagIcons, useDataAge } from '@/components/MetaValue'
import { Panel } from '@/components/ui/panel'
import type { EconEvent } from '@/types/schema'

const BLACKOUT_S = 30 * 60  // fenêtre Tier-1 ±30 min (reference/MANIFEST §Sony·SVS)

const TIER: Record<number, { squares: string; word: string; cls: string }> = {
  1: { squares: '▣▣▣', word: 'FORT', cls: 'text-risk-red border-risk-red/60' },
  2: { squares: '▣▣', word: 'MODÉRÉ', cls: 'text-risk-yellow border-risk-yellow/60' },
  3: { squares: '▣', word: 'FAIBLE', cls: 'text-term-dim border-term-border' },
}

/** Compte à rebours précis (H/M/S) vers un `ts` connu. Passé → « il y a … ». */
function countdown(secs: number): { label: string; past: boolean } {
  const past = secs < 0
  const a = Math.abs(secs)
  const h = Math.floor(a / 3600), m = Math.floor((a % 3600) / 60), s = Math.floor(a % 60)
  const core = h > 0
    ? `${h}h${String(m).padStart(2, '0')}`
    : `${m}m${String(s).padStart(2, '0')}`
  return { label: past ? `-${core}` : core, past }
}

function Row({ e, now, next }: { e: EconEvent; now: number; next: boolean }) {
  const t = TIER[e.tier] ?? TIER[3]
  const { label, past } = countdown(e.ts - now)
  return (
    <div className={cn('grid h-[15px] grid-cols-[62px_54px_1fr_34px] items-center gap-x-1.5 border-l-2 pl-1 font-mono text-xxs tabular-nums',
      e.tier === 1 ? 'border-l-risk-red/70' : e.tier === 2 ? 'border-l-risk-yellow/60' : 'border-l-term-border',
      next && 'bg-term-panel2', past && 'opacity-45')}>
      <span className={cn('text-right', past ? 'text-term-faint' : next ? 'text-term-text font-bold' : 'text-term-dim')}
        aria-label={past ? 'passé' : 'compte à rebours'}>
        {past ? label : `T−${label}`}
      </span>
      {/* Tier jamais par la couleur seule : carrés pleins (forme) + code texte (§3). */}
      <span className={cn('inline-flex items-center gap-1 rounded-sm border px-1 leading-none', t.cls)}
        title={`impact liquidité ${t.word}`}>
        <span aria-hidden>{t.squares}</span><span className="font-bold">T{e.tier}</span>
      </span>
      <span className="truncate text-term-text" title={e.name}>{e.name}</span>
      <span className="text-right text-term-faint">{e.region}</span>
    </div>
  )
}

export function EconCalendarPanel() {
  const meta = useTerminal((s) => s.econ_calendar?.events)
  const now = useTerminal(serverNow)      // temps serveur estimé → countdown live précis
  const age = useDataAge(meta)
  const stale = meta?.freshness === 'STALE'
  // « Événements PRÉVUS » : à venir + passé récent encore dans la fenêtre ±30 min (le
  // blackout T1 est symétrique) ; le passé lointain (hors fenêtre) est masqué, pas
  // pertinent pour la liquidité. Tri chronologique déjà fait côté moteur.
  const all = (meta?.value ?? []) as EconEvent[]
  const events = all.filter((e) => e.ts > now - BLACKOUT_S)
  // Prochain événement à venir (le plus proche avec ts > now) pour le surlignage.
  const nextTs = events.find((e) => e.ts > now)?.ts
  // Fenêtre blackout T1 : un événement Tier 1 à ±30 min. FACTUEL, pas un verrou Phase 0.
  const t1Window = events.some((e) => e.tier === 1 && Math.abs(e.ts - now) <= BLACKOUT_S)

  return (
    <Panel code="EC" title="Calendrier éco · Macro/Géo" block="econ_calendar.events" accent="none"
      right={meta ? <FlagIcons meta={meta} /> : undefined}>
      {!meta || meta.freshness === 'ABSENT' || !meta.value ? (
        <div className="grid h-full min-h-16 place-items-center">
          <span className="absent-pulse font-mono text-xs font-bold text-absent">PAS DE DONNÉES</span>
        </div>
      ) : (
        <div className={cn('flex min-h-0 flex-col', stale && 'opacity-60')}>
          {stale && (
            <p className="mb-1 border border-stale/50 px-1 py-0.5 text-center font-mono text-xxs uppercase text-stale">
              calendrier périmé {fmtAge(age)} — dernière image connue
            </p>
          )}
          {t1Window && (
            <p className="mb-1 flex items-center justify-center gap-1 border border-risk-red/60 bg-risk-red/10 px-1 py-0.5 text-center font-mono text-xxs font-bold uppercase text-risk-red"
              title="Un événement Tier 1 est dans la fenêtre ±30 min — filtre de timing Sony (AUTORITÉ). Information : Phase 0 reste le seul verrou.">
              ⚠ fenêtre news T1 · ±30 min — filtre Sony
            </p>
          )}
          <div className="grid grid-cols-[62px_54px_1fr_34px] gap-x-1.5 border-l-2 border-l-transparent pb-0.5 pl-1 font-mono text-xxs uppercase text-term-faint">
            <span className="text-right">échéance</span><span>impact</span>
            <span>événement</span><span className="text-right">zone</span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {events.length === 0 ? (
              <p className="py-2 text-center font-mono text-xxs text-term-faint">
                aucun événement programmé dans la fenêtre
              </p>
            ) : events.map((e) => (
              <Row key={`${e.ts}-${e.name}-${e.region}`} e={e} now={now} next={e.ts === nextTs} />
            ))}
          </div>
          <p className="mt-1 border-t border-term-border pt-1 text-xxs text-term-faint">
            événements programmés — impact liquidité, jamais un ordre ; T1 ±30 min = filtre Sony (§2.1)
          </p>
        </div>
      )}
    </Panel>
  )
}
