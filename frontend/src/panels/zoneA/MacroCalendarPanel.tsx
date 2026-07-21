/** Panneau MCAL — Calendrier économique (D-040) — lit UN champ : `macro_calendar` (CLAUDE §1).
 *  Publications TRADABLES (distinct d'EC/D-027, macro/géo systémique) ordonnées chronologiquement :
 *  compte à rebours dynamique (dérivé côté client), jauge d'impact HIGH/MED/LOW (couleur + points +
 *  texte, jamais la couleur seule §3), consensus/previous/actual + ÉCART de surprise (signé). Les
 *  annonces HIGH dans la fenêtre blackout ±15 min sont surlignées (elles pilotent le Risk Guard →
 *  Phase 0). LECTURE SEULE (§2.1). FAIL-CLOSED (§3) : périmé → FIGÉ ; vide → « PAS DE DONNÉES ». */
import { Fragment } from 'react'
import { cn } from '@/lib/utils'
import { serverNow, useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { Impact, MacroRelease } from '@/types/schema'

const PAUSE_WINDOW = 900   // ±15 min (miroir de MACRO_PAUSE_WINDOW_S backend)

function num(v: number | null | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)) : '·'
}
function signed(v: number | null | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? (v > 0 ? '+' : '') + (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)) : '·'
}
function fmtDur(s: number): string {
  const a = Math.abs(Math.round(s)), m = Math.floor(a / 60), h = Math.floor(m / 60)
  return h > 0 ? `${h}h${String(m % 60).padStart(2, '0')}` : `${m}m${String(a % 60).padStart(2, '0')}s`
}

// jauge d'impact : couleur + points remplis + texte (§3, jamais la couleur seule)
const IMPACT: Record<Impact, { cls: string; dots: string; label: string }> = {
  HIGH: { cls: 'text-risk-red', dots: '●●●', label: 'HIGH' },
  MED: { cls: 'text-risk-yellow', dots: '●●○', label: 'MED' },
  LOW: { cls: 'text-term-dim', dots: '●○○', label: 'LOW' },
}

export function MacroCalendarPanel() {
  const mc = useTerminal((s) => s.macro_calendar)
  const now = useTerminal((s) => serverNow(s))   // re-render chaque seconde (compte à rebours)
  const fresh = mc?.freshness
  // /devil : filtre les entrées non-objet (une release corrompue/null crasherait `e.impact`)
  const events: MacroRelease[] = Array.isArray(mc?.value?.events)
    ? mc!.value!.events.filter((e): e is MacroRelease => !!e && typeof e === 'object')
    : []
  const noData = fresh === 'ABSENT' || events.length === 0
  // divide passé / à venir : index du 1er événement futur (les events sont triés chrono)
  const firstFuture = events.findIndex((e) => Number.isFinite(e.ts) && e.ts - now >= 0)

  return (
    <Panel code="MCAL" title="Calendrier économique" block="macro_calendar" accent="none" owner="S1 + S2"
      right={<span className="tabular-nums text-xxs text-term-faint">{events.length} publi.</span>}>
      <div className={cn('relative h-full min-h-0 overflow-auto', fresh === 'STALE' && 'opacity-60')}>
        <table className="w-full border-collapse text-right font-mono text-xxs tabular-nums">
          <thead className="sticky top-0 z-10 bg-term-panel text-term-faint">
            <tr>
              <th className="px-1 text-left font-normal">ÉCHÉANCE</th>
              <th className="px-1 text-center font-normal">IMP.</th>
              <th className="px-1 text-left font-normal">ÉVÉNEMENT</th>
              <th className="px-1 font-normal">PRÉC</th>
              <th className="px-1 font-normal">CONS</th>
              <th className="px-1 font-normal">ACTUEL</th>
              <th className="px-1 font-normal">SURPR</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e, i) => {
              const imp = IMPACT[e.impact] ?? IMPACT.LOW
              const delta = Number.isFinite(e.ts) ? e.ts - now : NaN
              const past = delta < 0
              const blackout = e.impact === 'HIGH' && Number.isFinite(delta) && Math.abs(delta) <= PAUSE_WINDOW
              const next = i === firstFuture && !blackout           // prochaine échéance à venir
              const sur = e.surprise
              return (
                <Fragment key={i}>
                  {/* séparateur MAINTENANT — divide net passé (au-dessus, estompé) / à venir */}
                  {i === firstFuture && firstFuture > 0 && (
                    <tr aria-hidden><td colSpan={7} className="border-t border-router/50 px-1 py-px text-center text-xxs font-bold tracking-widest text-router">▸ MAINTENANT</td></tr>
                  )}
                  <tr className={cn('border-t border-term-border/40',
                    blackout && 'bg-risk-red/10', next && 'bg-term-grid/40',
                    !blackout && past && 'opacity-40')}>
                    <td className={cn('whitespace-nowrap px-1 text-left tabular-nums',
                      blackout ? 'font-bold text-risk-red' : next ? 'font-semibold text-term-text' : 'text-term-dim')}>
                      {!Number.isFinite(delta) ? '·' : past ? `+${fmtDur(delta)}` : fmtDur(delta)}
                      {blackout && <span title="Fenêtre blackout ±15 min — Phase 0 BLOCKED"> ⏸</span>}
                    </td>
                    <td className={cn('px-1 text-center tracking-tighter', imp.cls)} title={imp.label}>{imp.dots}</td>
                    <td className="max-w-0 truncate px-1 text-left text-term-text" title={e.name}>
                      {e.name}<span className="text-term-faint"> {e.country ?? ''}</span>
                    </td>
                    <td className="px-1 text-right text-term-dim">{num(e.previous)}</td>
                    <td className="px-1 text-right text-term-dim">{num(e.consensus)}</td>
                    <td className={cn('px-1 text-right', e.actual != null ? 'font-semibold text-term-text' : 'text-term-faint')}>{num(e.actual)}</td>
                    <td className={cn('px-1 text-right font-semibold', sur == null ? 'font-normal text-term-faint'
                      : sur > 0 ? 'bg-[rgba(52,211,153,0.10)] text-risk-green'
                        : sur < 0 ? 'bg-[rgba(248,113,113,0.10)] text-risk-red' : 'text-term-dim')}
                      title={sur == null ? 'surprise indisponible' : sur > 0 ? 'dépasse le consensus' : sur < 0 ? 'sous le consensus' : 'conforme'}>
                      {sur != null && sur > 0 && <span aria-hidden>▲</span>}{sur != null && sur < 0 && <span aria-hidden>▼</span>}{signed(sur)}
                    </td>
                  </tr>
                </Fragment>
              )
            })}
          </tbody>
        </table>
        {noData && (
          <div className="absolute inset-0 grid place-items-center">
            <span className="absent-pulse font-mono text-xs font-bold text-absent">PAS DE DONNÉES</span>
          </div>
        )}
        {fresh === 'STALE' && (
          <span className="absolute right-1 top-1 border border-stale/50 px-1 text-xxs font-bold text-stale">FIGÉ</span>
        )}
      </div>
    </Panel>
  )
}
