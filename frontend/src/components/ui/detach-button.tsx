/** Bouton de détachement d'un panneau (D-117).
 *
 *  Deux refus qui donnent au bouton sa valeur :
 *
 *  1. **Il ne s'affiche pas dans une fenêtre DÉJÀ détachée.** Détacher un panneau détaché
 *     n'a pas de sens, et le proposer ferait douter de ce qu'on regarde.
 *  2. **Une popup bloquée est DITE.** `window.open` rend `null` quand le navigateur refuse.
 *     Rester muet laisserait l'opérateur chercher une fenêtre qui n'existe pas — sur un poste
 *     multi-écran, il la chercherait littéralement des yeux ailleurs.
 */
import { useState } from 'react'
import { detachedPanelId, openDetached } from '@/lib/detach'
import { cn } from '@/lib/utils'

export function DetachButton({ panelId }: { panelId: string }) {
  const [bloque, setBloque] = useState(false)
  const dansUneFenetreDetachee = detachedPanelId(
    typeof location === 'undefined' ? '' : location.search) !== null

  if (dansUneFenetreDetachee) return null

  return (
    <button
      type="button"
      data-testid={`detach-${panelId}`}
      title={bloque
        ? 'la fenêtre a été BLOQUÉE par le navigateur — autoriser les popups pour ce site'
        : 'ouvrir ce panneau dans une fenêtre indépendante'}
      onClick={() => setBloque(openDetached(panelId) === null)}
      className={cn('shrink-0 rounded-sm border px-1 text-xxs leading-4',
        bloque ? 'border-bias-down/70 text-bias-down' : 'border-term-border text-term-faint',
        'hover:border-term-dim hover:text-term-dim')}
    >
      {bloque ? <span>⚠ bloquée</span> : <span aria-hidden>⧉</span>}
      <span className="sr-only">détacher</span>
    </button>
  )
}
