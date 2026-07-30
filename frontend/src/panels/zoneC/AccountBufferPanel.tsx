/** Panneau C5 — COMPTE & DISTANCE VERS LA MORT (D-051) — lit UN champ : `account_state`
 *  (CLAUDE §1). Trois blocs, du plus vital au plus détaillé :
 *
 *  1. ÉQUITÉ — valeur USD + P&L du jour signé (vs `day_start_equity`), badge de connectivité
 *     NT8 (frais / périmé-déconnecté).
 *  2. JAUGE DE BUFFER — « distance vers la mort » : barre `buffer / buffer_initial` (le buffer
 *     À L'OUVERTURE du jour est le dénominateur honnête, D-051). Paliers de la spec :
 *     > 60 % sain · 30–60 % réduite · < 30 % critique (clignotant) · ≤ 0 → BLOQUÉ.
 *  3. PROCHAIN TICKET — la taille pré-calculée sur le stop de RÉFÉRENCE (3 ticks MES) :
 *     l'opérateur voit sa capacité AVANT qu'une alerte tombe. Rejet du RiskSizer → badge de
 *     rejet explicite (MARGE INSUFFISANTE / DONNÉES INVALIDES / TAILLE INVRAISEMBLABLE) au
 *     lieu d'une taille.
 *
 *  §3 — jamais la couleur seule : chaque palier porte un LIBELLÉ + une ICÔNE ; les grandeurs
 *  absentes s'affichent en tiret neutre. FAIL-CLOSED : source déconnectée ou périmée →
 *  « CONNECTIVITÉ NT8 REQUISE » et AUCUNE grandeur affichée (jamais une équité fossile).
 *  LECTURE SEULE (§2.1) : ce panneau observe, il ne passe aucun ordre. */
import { Panel } from '@/components/ui/panel'
import { TIER_STYLE, bufferRatio, bufferTier, isLive, ticketDisplay, usd, usdSigned } from '@/lib/account'
import { cn } from '@/lib/utils'
import { useTerminal } from '@/store/terminal'

export function AccountBufferPanel() {
  const acc = useTerminal((s) => s.account_state)
  const live = isLive(acc)
  const tier = bufferTier(acc)
  const style = TIER_STYLE[tier]
  const ratio = bufferRatio(acc)
  const ticket = acc?.next_ticket
  const display = ticketDisplay(acc)
  const pnl = acc?.day_pnl ?? null
  const pnlUp = typeof pnl === 'number' && pnl > 0

  return (
    <Panel code="C5" title="Compte · distance vers la mort" block="account_state"
      right={
        <span data-testid="nt8-link"
          className={cn('inline-flex items-center gap-1 text-xxs font-semibold',
            live ? 'text-risk-green' : 'text-risk-red')}
          title={live ? 'Flux compte NT8 frais (< 15 s)'
            : 'Aucun état de compte exploitable — périmé ou déconnecté (fail-closed)'}>
          <span aria-hidden>{live ? '◉' : '◌'}</span>{live ? 'NT8 FRAIS' : 'NT8 ABSENT'}
        </span>
      }>
      {!live ? (
        // Fail-closed : aucune valeur, un message ACTIONNABLE (§3 + Loop 5 « une erreur dit quoi faire »)
        <div className="grid h-full place-items-center px-2 text-center" data-testid="account-offline">
          <div>
            <div className="absent-pulse font-mono text-xs font-bold text-absent">
              ⛔ CONNECTIVITÉ NT8 REQUISE
            </div>
            <div className="mt-1 text-xxs text-term-dim">
              Aucun état de compte frais — le dimensionnement et l'émission de propositions
              sont suspendus (on ne trade jamais à l'aveugle).
            </div>
          </div>
        </div>
      ) : (
        <div className="flex h-full min-h-0 flex-col gap-2">
          {/* 1. ÉQUITÉ + P&L du jour */}
          <div className="flex items-baseline justify-between gap-2 border-b border-term-border pb-1">
            <div className="min-w-0">
              <div className="text-xxs text-term-faint">ÉQUITÉ</div>
              <div className="truncate font-mono text-2xl font-bold tabular-nums text-term-text"
                data-testid="equity">{usd(acc?.current_equity)}<span className="text-xs text-term-dim"> $</span></div>
            </div>
            <div className="min-w-0 text-right">
              <div className="text-xxs text-term-faint">P&amp;L DU JOUR</div>
              <div data-testid="day-pnl"
                className={cn('truncate font-mono text-lg font-bold tabular-nums',
                  pnl === 0 || pnl == null ? 'text-term-dim'
                    : pnlUp ? 'text-risk-green' : 'text-risk-red')}>
                <span aria-hidden>{pnl == null || pnl === 0 ? '' : pnlUp ? '▲ ' : '▼ '}</span>
                {usdSigned(pnl)}<span className="text-xs"> $</span>
              </div>
            </div>
          </div>

          {/* 2. JAUGE — distance vers la mort */}
          <div>
            <div className="flex items-baseline justify-between gap-2 text-xxs">
              <span className="truncate text-term-faint">MARGE AVANT BLOCAGE</span>
              <span className={cn('shrink-0 font-bold', style.text)} data-testid="buffer-tier">
                <span aria-hidden>{style.icon} </span>{style.label}
                {ratio != null && <span className="ml-1 tabular-nums font-normal text-term-dim">
                  {(ratio * 100).toFixed(0)} %</span>}
              </span>
            </div>
            <div className="mt-0.5 h-3 w-full overflow-hidden border border-term-border bg-term-panel2">
              {tier === 'DEAD' ? (
                <div className="grid h-full place-items-center bg-risk-red/25 text-xxs font-black text-risk-red"
                  data-testid="buffer-dead">⛔ BLOQUÉ · MARGE ÉPUISÉE</div>
              ) : ratio == null ? (
                // Ratio INDÉTERMINABLE : une barre pleine (même grise) se lirait « 100 % de
                // marge » — on affiche l'ignorance en toutes lettres (§3, /devil).
                <div className="grid h-full place-items-center bg-stale/20 text-xxs font-bold text-stale"
                  data-testid="buffer-indeterminate">? MARGE INDÉTERMINABLE</div>
              ) : (
                <div data-testid="buffer-bar" role="progressbar"
                  aria-valuenow={Math.round(ratio * 100)}
                  aria-valuemin={0} aria-valuemax={100} aria-label="Marge avant blocage"
                  className={cn('h-full transition-[width] duration-300', style.bar,
                    style.blink && 'animate-pulse')}
                  style={{ width: `${ratio * 100}%` }} />
              )}
            </div>
            <div className="mt-0.5 flex justify-between gap-2 text-xxs tabular-nums text-term-dim">
              <span className="truncate" data-testid="buffer-abs">{usd(acc?.buffer)} $ / {usd(acc?.buffer_initial)} $</span>
              <span className="truncate" title="Plancher de drawdown (campagne) — la frontière la plus dure">
                plancher {usd(acc?.drawdown_floor)} $
              </span>
            </div>
          </div>

          {/* 3. PROCHAIN TICKET — capacité pré-calculée */}
          <div className="mt-auto border-t border-term-border pt-1">
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-xxs text-term-faint">
                PROCHAIN TICKET · stop réf. {ticket?.stop_ticks ?? '·'} ticks {ticket?.instrument ?? ''}
              </span>
              {typeof ticket?.risk_allowed === 'number' && (
                <span className="shrink-0 text-xxs tabular-nums text-term-dim">
                  risque {usd(ticket.risk_allowed)} $ (1/5)
                </span>
              )}
            </div>
            {/* La taille n'est affichée que si le sizer l'a approuvée DES DEUX CÔTÉS
                (`ticketDisplay`) — un payload contradictoire ne peut plus montrer un lot refusé. */}
            {display.kind === 'SIZE' ? (
              <div className="truncate font-mono text-xl font-bold tabular-nums text-router"
                data-testid="next-contracts">
                {display.contracts} contrat{display.contracts > 1 ? 's' : ''}
              </div>
            ) : (
              <div className="mt-0.5 inline-flex max-w-full items-center gap-1 border border-risk-red/60 px-1 text-xs font-bold text-risk-red"
                data-testid="next-reject">
                <span aria-hidden>⛔</span><span className="truncate">{display.label}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  )
}
