---
name: design
description: Langage visuel du terminal Cholismo par la Loop 6 (CLAUDE §13) — « inspiré des terminaux financiers, jamais copié ». À utiliser avant toute évolution UI. On emprunte l'IDÉE (densité, clavier-first, couleur sémantique), jamais l'EXPRESSION protégée (charte signature, codes propriétaires, layout/logo/nom identifiable). Documente dans docs/design-language.md.
argument-hint: <zone/vue à concevoir>
---

# /design — Loop 6 · langage visuel & inspiration

**Inspiré des terminaux financiers pour leurs principes — jamais copié.** L'IDÉE, jamais l'EXPRESSION protégée.

## Étapes
1. **Extraire les principes, pas les pixels** — densité tabulaire, clavier-first, latence basse, monospace pour les chiffres, couleur *sémantique* (doublée forme/icône), panneaux composables.
2. **Traduire en identité propre** — design tokens cholismo, nomenclature de commandes maison.
3. **Checklist anti-copie** (ci-dessous) — au moindre doute, on s'éloigne.
4. **Documenter** — `docs/design-language.md` : chaque emprunt justifié, chaque élément visible original.

## Checklist anti-copie (bloquante)
- [ ] Aucune **charte de couleurs signature** reprise d'un produit identifiable.
- [ ] Aucun **code de commande propriétaire** — p. ex. **`<GO>` de Bloomberg est INTERDIT** dans l'UI ; le GO/NO-GO *métier* (verdict Phase 0) reste, c'est un terme du domaine, pas une marque.
- [ ] Aucun **layout / logo / nom** identifiable à un terminal existant.
- [ ] Nommer un terminal (Bloomberg, Eikon, FactSet…) reste OK **dans la doc interne** comme source d'inspiration justifiée (`DECISIONS.md §D-000`), jamais rendu dans le produit.

## Sortie
Design distinctement **cholismo**, chaque emprunt justifié, chaque élément visible original.

## Garde-fou
On emprunte l'IDÉE, jamais l'EXPRESSION protégée. Doute = on s'éloigne et on trace la décision.
