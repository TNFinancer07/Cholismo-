/** IA — Alertes IA · Liquidity Sweep, lisant UN champ : `liquidity_sweep` (D-028).
 *  Détecteur LangGraph DÉTERMINISTE (pas un LLM) : « sans hallucination », §2.8. Advisory
 *  async — informe, ne bloque jamais, n'exécute aucun ordre (§2.1). Ergonomie NON-INTRUSIVE :
 *  un bandeau de statut (jamais de modale), pas de clignotement agressif ; CROSSED_BOOK
 *  (carnet croisé, sévère) et WIDE_SPREAD (spread large) distingués par des chips colorés
 *  — jamais la couleur seule (icône + texte + bordure, §3). Hiérarchie (Loop 5) : CROSSED
 *  = chip REMPLIE + liseré rouge + « dislocation » ; WIDE = contour ambre. Feed en grille à
 *  colonnes fixes (heure + glyphe de sens alignés) pour la lecture périphérique ; direction
 *  ▲offre/▼demande identifiable SANS lire (glyphe + couleur + position, §3). Fail-closed
 *  honnête : détecteur muet = bandeau muet ; « impossible à évaluer » ≠ « aucun sweep ». */
import { cn } from '@/lib/utils'
import { fmtAge, fmtSigned } from '@/lib/format'
import { serverNow, useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { LiquiditySweepAlert } from '@/types/schema'

const SWEEP_MUTE_S = 5  // ~5 ticks détecteur (1 s) sans analyse → muet

// Hiérarchie de sévérité (Loop 5) : CROSSED_BOOK = chip REMPLIE (le plus lourd visuellement,
// dislocation extrême) ; WIDE_SPREAD = contour ambre (avertissement) ; TAPE_BURST = discret.
// Le poids visuel (rempli > contour > discret) encode la sévérité en plus de la couleur.
const TRIGGER: Record<string, { label: string; cls: string; icon: string }> = {
  CROSSED_BOOK: { label: 'Carnet croisé', icon: '⚠',
    cls: 'text-risk-red border-risk-red/70 bg-risk-red/15 font-bold' },
  WIDE_SPREAD: { label: 'Spread large', icon: '↔',
    cls: 'text-risk-yellow border-risk-yellow/50' },
  TAPE_BURST: { label: 'Rafale', icon: '⇶', cls: 'text-term-dim border-term-border/60' },
}

type Sev = 'crossed' | 'wide' | 'burst'
function severityOf(trigger: string): Sev {
  if (trigger.includes('CROSSED_BOOK')) return 'crossed'
  if (trigger.includes('WIDE_SPREAD')) return 'wide'
  return 'burst'
}
// Liseré gauche par sévérité → lecture en VISION PÉRIPHÉRIQUE : le bord gauche du feed révèle
// d'un coup d'œil la répartition rouge/ambre/neutre, sans lire (§3 forme + position).
const SEV_STRIPE: Record<Sev, string> = {
  crossed: 'border-l-risk-red', wide: 'border-l-risk-yellow', burst: 'border-l-term-border',
}

// Direction glyphe-forward : ▲ offre (agression acheteuse) / ▼ demande (agression vendeuse).
// Identifiable SANS lire — glyphe + couleur + position fixe (§3, jamais la couleur seule).
function dirInfo(d: string | null) {
  if (d === 'ASK_SWEEP')
    return { glyph: '▲', label: 'offre', title: 'agression acheteuse — offre balayée', cls: 'text-risk-green' }
  if (d === 'BID_SWEEP')
    return { glyph: '▼', label: 'demande', title: 'agression vendeuse — demande balayée', cls: 'text-risk-red' }
  return { glyph: '·', label: 'n/d', title: 'sens indéterminé — pas de tape pour confirmer', cls: 'text-term-faint' }
}

function fmtClock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('en-GB', { hour12: false })
}

function TriggerChips({ trigger }: { trigger: string }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {trigger.split('+').filter(Boolean).map((t) => {
        const m = TRIGGER[t] ?? { label: t, cls: 'text-term-dim border-term-border', icon: '·' }
        return (
          <span key={t} className={cn('inline-flex items-center gap-1 rounded-sm border px-1 leading-none', m.cls)}>
            <span aria-hidden>{m.icon}</span>{m.label}
          </span>
        )
      })}
    </span>
  )
}

function AlertRow({ a, active }: { a: LiquiditySweepAlert; active: boolean }) {
  // Grille à colonnes fixes (heure + glyphe de sens alignés verticalement dans tout le feed
  // → scan périphérique). Liseré gauche = sévérité. news = min-w-0 flex-1 truncate (tronque
  // d'abord), overflow-hidden clippe aux largeurs extrêmes (leçon /devil OB : jamais de
  // débordement du body).
  const dir = dirInfo(a.direction)
  return (
    <div className={cn('grid h-[15px] grid-cols-[44px_11px_1fr] items-center gap-x-1.5 overflow-hidden border-l-2 pl-1 font-mono text-xxs',
      SEV_STRIPE[severityOf(a.trigger)], active && 'bg-term-panel2')}>
      <span className="tabular-nums text-term-faint">{fmtClock(a.ts)}</span>
      <span className={cn('text-center font-bold', dir.cls)} title={dir.title} aria-label={dir.title}>
        {dir.glyph}
      </span>
      <span className="flex min-w-0 items-center gap-1.5 overflow-hidden">
        <span className="shrink-0"><TriggerChips trigger={a.trigger} /></span>
        {a.spread_width !== null && (
          <span className="shrink-0 tabular-nums text-term-dim" title="spread en ticks (négatif = croisé)">
            {fmtSigned(a.spread_width, 1)}t
          </span>
        )}
        {a.news_context && (
          <span className="min-w-0 flex-1 truncate text-term-faint" title={a.news_context}>· {a.news_context}</span>
        )}
      </span>
    </div>
  )
}

export function AiAlertsPanel() {
  const sw = useTerminal((s) => s.liquidity_sweep)
  const now = useTerminal(serverNow)
  const age = sw?.last_compute_ts != null ? Math.max(0, now - sw.last_compute_ts) : null
  const mute = age === null || age > SWEEP_MUTE_S
  const severe = !!sw?.alert && sw.alert.trigger.includes('CROSSED_BOOK')

  return (
    <Panel code="IA" title="Alertes IA · Sweep" block="liquidity_sweep" accent="none">
      {!sw || sw.last_compute_ts == null ? (
        <div className="grid h-full min-h-16 place-items-center">
          <span className="font-mono text-xxs text-term-faint">détecteur en attente…</span>
        </div>
      ) : (
        <div className={cn('flex min-h-0 flex-col', mute && 'opacity-60')}>
          {mute ? (
            <p className="mb-1 border border-absent/60 px-1 py-0.5 text-center font-mono text-xxs uppercase text-absent">
              détecteur muet — dernière analyse {fmtAge(age)}
            </p>
          ) : !sw.assessable ? (
            <p className="mb-1 border border-stale/50 px-1 py-0.5 text-center font-mono text-xxs uppercase text-stale">
              impossible à évaluer — données microstructure/news insuffisantes
            </p>
          ) : sw.triggered && sw.alert ? (
            <div className={cn('mb-1 border px-1.5 py-1',
              severe ? 'border-risk-red/70 bg-risk-red/15' : 'border-risk-yellow/60 bg-risk-yellow/10')}>
              <div className={cn('flex flex-wrap items-center gap-2 font-mono text-xxs font-bold uppercase',
                severe ? 'text-risk-red' : 'text-risk-yellow')}>
                {/* Sévère (croisé) = ⚠ + libellé « dislocation » ; avertissement = ◆.
                    Hiérarchie par teinte/remplissage/mot, PAS par animation (non-intrusif). */}
                <span aria-hidden>{severe ? '⚠' : '◆'}</span>
                {severe ? 'Sweep — dislocation' : 'Sweep actif'}
                <TriggerChips trigger={sw.alert.trigger} />
                {(() => {
                  const dir = dirInfo(sw.alert.direction)
                  return (
                    <span className={cn('inline-flex items-center gap-0.5', dir.cls)} title={dir.title}>
                      <span className="text-sm leading-none">{dir.glyph}</span>{dir.label}
                    </span>
                  )
                })()}
              </div>
              {sw.alert.news_context && (
                <p className="mt-0.5 font-mono text-xxs text-term-dim">news : {sw.alert.news_context}</p>
              )}
            </div>
          ) : (
            <p className="mb-1 border border-term-border px-1 py-0.5 text-center font-mono text-xxs uppercase text-term-dim">
              ✓ aucun sweep
            </p>
          )}

          <div className="min-h-0 flex-1 overflow-y-auto">
            {sw.recent.length === 0 ? (
              <p className="py-2 text-center font-mono text-xxs text-term-faint">aucune alerte récente</p>
            ) : sw.recent.map((a, i) => (
              <AlertRow key={`${a.ts}-${a.trigger}-${i}`} a={a} active={i === 0 && sw.triggered} />
            ))}
          </div>
          <p className="mt-1 border-t border-term-border pt-1 text-xxs text-term-faint">
            détecteur déterministe (LangGraph) · advisory, jamais un ordre (§2.1)
          </p>
        </div>
      )}
    </Panel>
  )
}
