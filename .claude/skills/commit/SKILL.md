---
name: commit
description: Produire un commit atomique et propre du terminal Cholismo. À utiliser en fin de Loop 1/2/3 une fois le dépôt vert. Un seul sujet par commit, message clair quoi + pourquoi, jamais de code cassé.
argument-hint: [message]
---

# /commit — transverse · commit atomique

Un commit cohérent, dépôt vert, message clair.

## Étapes
1. **Dépôt vert** — vérifier via `/done` avant de committer (tests + build + lint).
2. **Atomique** — un seul sujet. Deux sujets → deux commits. Jamais feature + refactor ensemble.
3. **Message** — quoi **et pourquoi**, en français, impératif. Référence le champ du schéma / la tâche.
4. **Indexer & committer** — `git add` ciblé (pas de `git add -A` aveugle), puis commit.

## Sortie
Un commit cohérent, dépôt vert, message clair et traçable.

## Garde-fous
- Jamais deux features à la fois, ni du code cassé.
- Développer sur la branche désignée ; ne pousser que sur elle. Pas de PR sans demande explicite.
- Un `git push` échoué pour raison réseau → retry avec backoff (2s/4s/8s/16s), pas au-delà.
