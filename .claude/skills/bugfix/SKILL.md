---
name: bugfix
description: Corriger un bug du terminal Cholismo par la Loop 2 (CLAUDE §13). À utiliser dès qu'un comportement est faux ou qu'un crash survient. Pas de fix sans repro ; on cible la cause racine, jamais le symptôme.
argument-hint: <description du bug>
---

# /bugfix — Loop 2 · correction de bug

Contrat : **Déclencheur → Étapes → Sortie → Garde-fous**. 3 itérations sans progrès → stop et remonte.

## Étapes
1. **Reproduire** — la suite d'actions minimale. Pas de fix sans repro.
2. **Capturer** — un test de régression qui échoue et fige le bug.
3. **Isoler** — la cause racine, pas le symptôme.
4. **Corriger** — le plus ciblé possible.
5. **Confirmer** — régression verte + toute la suite verte + essai manuel.
6. **Prévenir** — où ailleurs ce bug peut-il exister ? (mêmes patterns).

## Sortie
Repro impossible, test de régression vert, aucune régression ailleurs.

## Garde-fous
- **Jamais masquer le symptôme** : pas de `catch` vide, pas de défaut silencieux, pas de valeur inventée à la place d'une donnée absente (§3 fail-closed).
- Un fix ne doit pas relâcher un verrou dur (§2) : Phase 0 déterministe, append-only, aucun ordre passé.
