/** IA — Alertes IA · Liquidity Sweep, lisant UN champ : `liquidity_sweep` (D-028).
 *  Détecteur LangGraph DÉTERMINISTE (pas un LLM) : « sans hallucination », §2.8. Advisory
 *  async — informe, ne bloque jamais, n'exécute aucun ordre (§2.1). Ergonomie NON-INTRUSIVE :
 *  un bandeau de statut (jamais de modale), pas de clignotement agressif ; CROSSED_BOOK
 *  (carnet croisé, sévère) et WIDE_SPREAD (spread large) distingués par des chips colorés
 *  — jamais la couleur seule (icône + texte + bordure, §3). Fail-closed honnête : détecteur
 *  muet = bandeau muet ; « impossible à évaluer » ≠ « aucun sweep ». */
import { cn } from '@/lib/utils'
import { fmtAge, fmtSigned } from '@/lib/format'
import { serverNow, useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import type { LiquiditySweepAlert } from '@/types/schema'

const SWEEP_MUTE_S = 5  // ~5 ticks détecteur (1 s) sans analyse → muet

const TRIGGER: Record<string, { label: string; cls: string; icon: string }> = {
  CROSSED_BOOK: { label: 'Carnet croisé', cls: 'text-risk-red border-risk-red/60', icon: '⚠' },
  WIDE_SPREAD: { label: 'Spread large', cls: 'text-risk-yellow border-risk-yellow/60', icon: '↔' },
  TAPE_BURST: { label: 'Rafale', cls: 'text-term-text border-term-border', icon: '⇶' },
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

function Direction({ d }: { d: string | null }) {
  if (!d) return <span className="text-term-faint">—</span>
  const ask = d === 'ASK_SWEEP'
  // Sens jamais par la couleur seule : glyphe ▲/▼ + libellé (§3).
  return (
    <span className={cn('inline-flex items-center gap-0.5', ask ? 'text-risk-green' : 'text-risk-red')}
      title={ask ? 'agression acheteuse — offre balayée' : 'agression vendeuse — bid balayé'}>
      {ask ? '▲' : '▼'}{ask ? 'offre' : 'bid'}
    </span>
  )
}

function AlertRow({ a, active }: { a: LiquiditySweepAlert; active: boolean }) {
  // min-w-0 + overflow-hidden : au redimensionnement extrême, la news (priorité basse)
  // tronque d'abord (flex-1), le reste est shrink-0 et clippe — jamais de débordement
  // horizontal du body (leçon /devil OB). Chips en shrink-0 : l'info critique reste visible.
  return (
    <div className={cn('flex min-w-0 items-center gap-2 overflow-hidden border-l-2 py-0.5 pl-1 font-mono text-xxs',
      active ? 'border-l-risk-yellow bg-term-panel2' : 'border-l-term-border')}>
      <span className="shrink-0 tabular-nums text-term-faint">{fmtClock(a.ts)}</span>
      <span className="shrink-0"><TriggerChips trigger={a.trigger} /></span>
      <span className="shrink-0"><Direction d={a.direction} /></span>
      {a.spread_width !== null && (
        <span className="shrink-0 tabular-nums text-term-dim" title="spread en ticks (négatif = croisé)">
          {fmtSigned(a.spread_width, 1)}t
        </span>
      )}
      {a.news_context && (
        <span className="min-w-0 flex-1 truncate text-term-faint" title={a.news_context}>
          · {a.news_context}
        </span>
      )}
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
              severe ? 'border-risk-red/60 bg-risk-red/10' : 'border-risk-yellow/60 bg-risk-yellow/10')}>
              <div className={cn('flex flex-wrap items-center gap-2 font-mono text-xxs font-bold uppercase',
                severe ? 'text-risk-red' : 'text-risk-yellow')}>
                <span aria-hidden>◆</span>Sweep actif
                <TriggerChips trigger={sw.alert.trigger} />
                <Direction d={sw.alert.direction} />
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
