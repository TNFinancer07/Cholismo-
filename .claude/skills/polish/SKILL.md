---
name: polish
description: Polish UX du terminal Cholismo par la Loop 5 (CLAUDE §13). À utiliser une fois une feature fonctionnelle pour soigner latence perçue, messages, cohérence clavier/vocabulaire/couleur, sortie propre et découvrabilité. Lisibilité > décoration.
argument-hint: <feature/vue à soigner>
---

# /polish — Loop 5 · polish UX

Le « agréable à utiliser », après le « ça marche ».

## Étapes
1. **Latence perçue** — feedback < 100 ms (cohérent §7 ; le hot path reste < ~200 ms).
2. **Messages** — lisibles et actionnables (français, §5). Une erreur dit quoi faire.
3. **Cohérence** — raccourcis clavier, vocabulaire, **code couleur sémantique** (§3 : VERT/JAUNE/ROUGE **jamais par la seule couleur** → toujours forme + icône + position ; Router en or/bordure).
4. **Sortie propre** — Ctrl-C, quit, fermeture SSE, pas d'état cassé.
5. **Découvrabilité** — help / `?`, barre de touches visible, mnémoniques listés.

## Sortie
Un utilisateur sans doc comprend et **n'est jamais bloqué sans message**.

## Garde-fous
- **Lisibilité > décoration.** Pas de « joli » au prix de la clarté ni de la densité utile.
- Le polish ne masque jamais un état dur (§2) : un ROUGE fail-closed reste visible et honnête.
