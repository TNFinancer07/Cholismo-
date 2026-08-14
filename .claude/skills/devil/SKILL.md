---
name: devil
description: Revue critique avant commit du terminal Cholismo par la Loop 4 (CLAUDE §13). À utiliser avant de clôturer une feature/un fix pour attaquer son propre code. Revue honnête, jamais complaisante.
argument-hint: [cible optionnelle]
---

# /devil — Loop 4 · devil's advocate

Attaquer son propre code **avant** le commit.

## Étapes
1. **Attaquer** — 3 façons concrètes de casser. Pour Cholismo, penser : entrée vide/énorme, saisie invalide, **coupure du flux marché** (source STALE/ABSENT), désync d'horloge, valeurs contradictoires inter-sources, terminal redimensionné, **Ctrl-C au mauvais moment** (pendant un fetch/tick).
2. **Cas limite oublié** — état partagé (race), ordre des events, ressource non libérée, backpressure (tick suivant avant la fin du précédent).
3. **Questionner le design** — plus simple ? un panneau non traçable au schéma qui traîne ?
4. **Intégrer / documenter** — corriger ou tracer le risque assumé (`DECISIONS.md`).

## Sortie
Les 3 scénarios de casse sont **gérés ou documentés hors-scope**.

## Garde-fous
- Revue honnête, **jamais de complaisance**. Le doute réel finit tracé, pas enterré.
- Vérifier que chaque chemin d'échec **fail-close** (§2/§3) : en cas de doute, l'UI montre BLOQUÉ / PAS DE DONNÉES, jamais une valeur inventée.

## Voir aussi
`/loop-check` pour l'audit systématique des boucles runtime (`RUNTIME_LOOPS.md`).
