/** CVD — CVD Footprint lisant UN champ : `s1_state.cvd_by_level` (D-029). Delta agresseur
 *  net PAR NIVEAU de prix, heatmap THERMIQUE vert (acheteur) / rouge (vendeur) : intensité
 *  ∝ |delta| relatif — MAIS jamais la couleur seule, le delta SIGNÉ est incrusté (§3, lisible
 *  sans percevoir la couleur). Échelle par prix décroissant (le plus haut en tête, façon DOM).
 *  Reset événementiel (news) affiché ; `capped` (suivi saturé) et `stale` (gelé) signalés
 *  honnêtement ; pas de niveau → PAS DE DONNÉES (§3). Temps réel via sélecteur zustand isolé
 *  (ne re-rend que ce panneau). Flux OBSERVÉ, jamais un ordre (§2.1). */
import { cn } from '@/lib/utils'
import { fmtAge, fmtInt, fmtNum, fmtSigned } from '@/lib/format'
import { serverNow, useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { CvdLevel } from '@/types/schema'

const GREEN = '52, 211, 153'   // risk-green — acheteur net
const RED = '248, 113, 113'    // risk-red — vendeur net

function Row({ le, maxAbs }: { le: CvdLevel; maxAbs: number }) {
  const buy = le.delta >= 0
  const intensity = maxAbs > 0 ? Math.min(1, Math.abs(le.delta) / maxAbs) : 0
  return (
    <div className="grid h-[15px] grid-cols-[62px_1fr] items-center gap-x-1 font-mono text-xxs tabular-nums">
      <span className="text-right text-term-dim">{fmtNum(le.price, 2)}</span>
      <div className="relative h-[13px] overflow-hidden rounded-sm border border-term-grid"
        style={{ backgroundColor: `rgba(${buy ? GREEN : RED}, ${(0.08 + intensity * 0.55).toFixed(2)})` }}
        title={`${fmtNum(le.price, 2)} : delta ${fmtSigned(le.delta, 0)} `
          + `(buy ${fmtInt(le.buy)} / sell ${fmtInt(le.sell)})`}>
        {/* Delta SIGNÉ incrusté : le signe porte le sens, lisible sans percevoir la couleur (§3). */}
        <span className={cn('absolute inset-0 grid place-items-center font-bold',
          buy ? 'text-risk-green' : 'text-risk-red')}>
          {fmtSigned(le.delta, 0)}
        </span>
      </div>
    </div>
  )
}

export function FootprintPanel() {
  const cvd = useTerminal((s) => s.s1_state?.cvd_by_level)
  const now = useTerminal(serverNow)
  const levels = cvd?.levels ?? []
  const rows = [...levels].sort((a, b) => b.price - a.price)   // prix décroissant, façon DOM
  const maxAbs = rows.reduce((m, le) => Math.max(m, Math.abs(le.delta)), 0)
  const sinceAge = cvd?.since_ts != null ? Math.max(0, now - cvd.since_ts) : null

  return (
    <Panel code="CVD" title="CVD Footprint" block="s1_state.cvd_by_level" accent="sony">
      {!cvd || rows.length === 0 ? (
        <div className="grid h-full min-h-16 place-items-center">
          <span className="absent-pulse font-mono text-xs font-bold text-absent">PAS DE DONNÉES</span>
        </div>
      ) : (
        <div className={cn('flex min-h-0 flex-col', cvd.stale && 'opacity-60')}>
          <div className="mb-1 flex items-center justify-between gap-2 font-mono text-xxs">
            <span className="shrink-0 text-term-faint">net cumulé</span>
            <span className={cn('shrink-0 font-bold tabular-nums',
              cvd.total_delta >= 0 ? 'text-risk-green' : 'text-risk-red')}>
              Δ {fmtSigned(cvd.total_delta, 0)}
            </span>
          </div>
          {cvd.reset_reason && (
            <p className="mb-1 truncate text-xxs text-term-faint"
              title={`accumulation depuis le reset : ${cvd.reset_reason}`}>
              depuis {sinceAge != null ? fmtAge(sinceAge) : '—'} · reset {cvd.reset_reason}
            </p>
          )}
          {cvd.stale ? (
            <p className="mb-1 border border-stale/50 px-1 py-0.5 text-center font-mono text-xxs uppercase text-stale">
              figé — flux tape périmé, dernière image
            </p>
          ) : cvd.capped && (
            <p className="mb-1 border border-term-border px-1 py-0.5 text-center font-mono text-xxs uppercase text-term-dim">
              suivi saturé — niveaux les plus actifs
            </p>
          )}
          <div className="grid grid-cols-[62px_1fr] gap-x-1 pb-0.5 font-mono text-xxs uppercase text-term-faint">
            <span className="text-right">prix</span><span>delta</span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {rows.map((le) => <Row key={le.price} le={le} maxAbs={maxAbs} />)}
          </div>
          <p className="mt-1 border-t border-term-border pt-1 text-xxs text-term-faint">
            delta agresseur/niveau — vert acheteur ▲ / rouge vendeur ▼ ; flux observé, jamais un ordre (§2.1)
          </p>
        </div>
      )}
    </Panel>
  )
}
