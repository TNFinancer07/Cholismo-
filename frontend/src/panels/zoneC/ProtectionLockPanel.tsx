/** Verrou de protection F6/F7 — GET /protection (D-113).
 *
 *  Existe pour une raison précise : sans lui, l'opérateur voit un setup **ne pas apparaître** et
 *  ne peut pas distinguer « aucun signal » de « signal ÉCARTÉ par un verrou ». Deux situations
 *  qui appellent des conduites opposées — attendre le prochain setup, ou comprendre qu'on est en
 *  pause forcée après deux pertes.
 *
 *  Le verrou n'est PAS désactivable depuis l'écran, et c'est le point : la discipline est dans
 *  l'infra, pas dans la volonté (`CLAUDE §6`). Ce panneau EXPLIQUE, il ne débloque pas.
 *
 *  LECTURE SEULE (§2.1). FAIL-CLOSED (§3) : état indisponible → « — », jamais « déverrouillé ». */
import { useEffect, useState } from 'react'
import { Panel } from '@/components/ui/panel'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

interface Rejection { reason: string | null; ts: number | null; setup_id: string | null }
interface Protection {
  consecutive_losses: number
  trades_today: number
  locked: boolean
  lock_reason: string | null
  seconds_remaining: number | null
  recent_rejections: Rejection[]
}

const MOTIFS: Record<string, string> = {
  F6_COOLDOWN_ACTIVE: 'verrou après 2 pertes consécutives',
  F7_FOMO_TIMEOUT: 'sweep trop ancien — entrer serait courir après le prix',
  F7_RESUBMIT_LOCKOUT: 'setup déjà refusé, re-soumission verrouillée',
}

export function libelleMotif(code: string | null | undefined): string {
  if (!code) return '—'
  return MOTIFS[code] ?? code
}

export function compteARebours(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s) || s <= 0) return '—'
  const m = Math.floor(s / 60)
  return m > 0 ? `${m} min ${String(Math.floor(s % 60)).padStart(2, '0')} s` : `${Math.floor(s)} s`
}

export function ProtectionLockPanel() {
  const [p, setP] = useState<Protection | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    let vivant = true
    const charge = () => api.protection<Protection>()
      .then((d) => { if (vivant) { setP(d); setErr(false) } })
      .catch(() => { if (vivant) setErr(true) })
    charge()
    const t = setInterval(charge, 5000)
    return () => { vivant = false; clearInterval(t) }
  }, [])

  return (
    <Panel code="C6" title="Verrous de protection · F6 · F7" block="projection Decision Log"
      accent="sony" detachId="C6">
      <div className="flex flex-col gap-1 p-1.5 text-xs">
        {err || !p ? (
          // Fail-closed : on ne dit JAMAIS « déverrouillé » quand on ne sait pas.
          <p className="text-term-faint" data-testid="lock-inconnu">
            — état des verrous indisponible (ne signifie pas « déverrouillé »)
          </p>
        ) : (
          <>
            <div className={cn('flex items-center gap-2 border p-1',
              p.locked ? 'border-bias-down/70 bg-bias-down/10' : 'border-term-border')}>
              <span aria-hidden className="text-sm">{p.locked ? '⛔' : '○'}</span>
              <span className={cn('font-bold', p.locked ? 'text-bias-down' : 'text-term-dim')}
                data-testid="lock-etat">
                {p.locked ? 'VERROUILLÉ' : 'aucun verrou actif'}
              </span>
              {p.locked && (
                <span className="text-term-dim" data-testid="lock-restant">
                  encore {compteARebours(p.seconds_remaining)}
                </span>
              )}
            </div>
            {p.locked && (
              <p className="text-xxs text-term-dim" data-testid="lock-motif">
                {libelleMotif(p.lock_reason)} — le verrou ne se désactive pas depuis l'écran
              </p>
            )}
            <table className="w-full text-xxs">
              <tbody>
                <tr className="border-t border-term-border/50">
                  <td className="py-0.5 text-term-dim">pertes consécutives (séance)</td>
                  <td className="py-0.5 text-right tabular-nums" data-testid="lock-pertes">
                    {p.consecutive_losses}
                  </td>
                </tr>
                <tr className="border-t border-term-border/50">
                  <td className="py-0.5 text-term-dim">trades du jour</td>
                  <td className="py-0.5 text-right tabular-nums">{p.trades_today}</td>
                </tr>
              </tbody>
            </table>
            {p.recent_rejections.length > 0 && (
              <div data-testid="lock-refus">
                <p className="text-xxs text-term-faint">setups écartés récemment</p>
                <ul className="text-xxs text-term-dim">
                  {p.recent_rejections.slice(0, 4).map((r, i) => (
                    <li key={`${r.ts}-${i}`}>· {libelleMotif(r.reason)}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </Panel>
  )
}
