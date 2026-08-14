/** Fenêtre détachée — un seul panneau, alimenté par rediffusion (D-116).
 *
 *  Elle n'ouvre AUCUNE connexion au backend : la fenêtre principale reste seule abonnée au SSE et
 *  rediffuse son instantané. Deux abonnements laisseraient deux fenêtres diverger — deux vérités
 *  affichées côte à côte sur le même bureau.
 *
 *  Le bandeau de synchronisation est en TÊTE et non en pied : sur un second moniteur regardé du
 *  coin de l'œil, ce qu'on lit en dernier, on ne le lit pas. */
import { useEffect, useState } from 'react'
import { PANEL_REGISTRY } from '@/panels/registry'
import type { PanelId } from '@/store/workspace'
import { useTerminal } from '@/store/terminal'
import { DetachChannel, SYNC_LABELS, syncStatus, type DetachMessage } from '@/lib/detach'
import { cn } from '@/lib/utils'

export function DetachedPanelWindow({ panelId }: { panelId: string }) {
  const [lastAt, setLastAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const set = useTerminal((s) => s.set)

  useEffect(() => {
    const ch = new DetachChannel()
    const off = ch.subscribe((m: DetachMessage) => {
      setLastAt(m.sentAt)
      // Rafraîchir l'horloge AVEC la réception. Sans cela, `now` (mis à jour à la seconde)
      // pouvait être antérieur à `sentAt`, et la garde « horodatage futur » rejetait un message
      // parfaitement légitime — la fenêtre restait « en attente » alors qu'elle recevait.
      setNow(Date.now())
      // L'instantané est appliqué TEL QUEL : la fenêtre détachée ne recalcule rien, sinon deux
      // fenêtres pourraient afficher deux résultats du même état.
      if (m.payload && typeof m.payload === 'object') set(m.payload as Record<string, unknown>)
    })
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => { off(); ch.close(); clearInterval(t) }
  }, [set])

  const def = PANEL_REGISTRY[panelId as PanelId]
  const statut = syncStatus(lastAt, now)
  const l = SYNC_LABELS[statut]
  const age = lastAt === null ? null : Math.max(0, Math.round((now - lastAt) / 1000))

  return (
    <div className="flex h-screen min-h-0 flex-col bg-term-bg text-term-text">
      {/* EN TÊTE : une fenêtre désynchronisée ressemble à un marché calme (D-073, transposé). */}
      <div className={cn('flex items-center gap-2 border-b border-term-border px-2 py-1 text-xxs',
        statut === 'LOST' && 'bg-bias-down/15', statut === 'STALE' && 'bg-gold/10')}
        data-testid="detach-sync" data-statut={statut} title={l.titre}>
        <span aria-hidden>{statut === 'LIVE' ? '●' : statut === 'UNKNOWN' ? '○' : '⚠'}</span>
        <span className={cn('font-bold', l.cls)}>{l.txt}</span>
        <span className="text-term-faint">
          {age === null ? "rien reçu" : `dernière synchro il y a ${age} s`}
        </span>
        <span className="ml-auto text-term-faint">{def?.label ?? panelId} · fenêtre détachée</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-1">
        {def ? <def.component /> : (
          <p className="p-2 text-xs text-term-faint" data-testid="detach-inconnu">
            panneau « {panelId} » inconnu — rien à afficher (aucun panneau de substitution)
          </p>
        )}
      </div>
    </div>
  )
}
