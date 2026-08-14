---
name: refactor
description: Refactor sûr du terminal Cholismo par la Loop 3 (CLAUDE §13). À utiliser pour clarifier du code SANS changer son comportement. Jamais refactor + feature dans le même commit.
argument-hint: <cible : fichier/module>
---

# /refactor — Loop 3 · refactor sûr

Changer la **forme**, jamais le **comportement**.

## Étapes
1. **Filet de sécurité** — des tests couvrant l'existant AVANT de toucher quoi que ce soit.
2. **Micro-étapes** — verts entre chaque.
3. **Zéro changement de comportement** — l'observable reste identique.
4. **Commit fréquent** — chaque étape verte est un commit (`/commit`).

## Sortie
Code plus clair, comportement identique prouvé par les tests, tout vert.

## Garde-fous
- **Jamais refactor + feature ensemble.**
- > 3 tests cassés d'un coup → reviens en arrière, redécoupe plus fin.
- Un refactor ne modifie pas un contrat dur (§2) : schéma, append-only, projections, Phase 0 restent équivalents.
