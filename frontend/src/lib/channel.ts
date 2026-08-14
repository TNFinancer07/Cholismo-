/** Santé des canaux SSE, côté lecture des panneaux.
 *
 *  Le canal LENT tourne à 15 s : à l'ouverture du terminal, un panneau qui en dépend affiche son
 *  écran vide pendant un tick entier. « PAS DE DONNÉES » est alors EXACT mais trompeur — c'est le
 *  même message qu'un flux réellement mort, et l'opérateur ne peut pas distinguer « attends » de
 *  « débogue ». On sépare donc les deux cas : tant qu'AUCUN événement lent n'est arrivé, le
 *  panneau dit qu'il attend ; ensuite seulement, l'absence devient une absence.
 *
 *  Ce n'est pas un adoucissement du fail-closed (§3) : aucune valeur n'est inventée, aucun état
 *  dur n'est masqué — seule la CAUSE affichée devient juste.
 */
import { useTerminal } from '@/store/terminal'

/** `true` tant qu'aucun événement du canal lent n'a été reçu depuis le montage. */
export function useSlowChannelPending(): boolean {
  return useTerminal((s) => s.lastSlowEventAt === 0)
}
