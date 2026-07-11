---
name: feature
description: Développer une feature du terminal Cholismo par la Loop 1 (CLAUDE §13). À utiliser quand on ajoute une tranche fonctionnelle — nouveau panneau, endpoint, projection. Un panneau = un bloc du ContextSchema ; une feature = un commit.
argument-hint: <description de la feature>
---

# /feature — Loop 1 · développement de feature

Opérationnalise la **§12** (méthode de travail) sous les garde-fous de la **§2** (contraintes dures).
Contrat : **Déclencheur → Étapes → Sortie → Garde-fous**. 3 itérations sans progrès mesurable → stop et remonte le blocage.

## Étapes (dans l'ordre)
1. **Clarifier** — 1 phrase de comportement voulu + cas limites, AVANT de coder. Ambigu ou contradiction de spec → question (§12). Sinon applique et note l'hypothèse dans `DECISIONS.md`.
2. **Plan** — la plus petite tranche livrable. Décris l'interface publique. Rappel : **un panneau lit UN champ du schéma** ; tout panneau non traçable au schéma ne doit pas exister (§1).
3. **Test d'abord** — au moins un test qui échoue et décrit le comportement (backend pytest / front vitest ou Playwright selon la surface).
4. **Implémenter** — le minimum pour passer au vert. Isole toute formule non figée (`v1 provisional`).
5. **Auto-revue** — relis le diff comme celui d'un inconnu.
6. **Vérifier** — tests + lint/tsc + **essai manuel réel** (lancer le backend + front, exercer le flux).
7. **Commit** — atomique, dépôt vert (`/commit`).

## Garde-fous (hérités §2)
- Aucune exécution d'ordre : Go/No-Go **enregistre**, ne trade pas.
- Fail-closed : donnée absente/périmée → jamais de valeur inventée (§3 « no signal without data »).
- Phase 0 déterministe inviolable ; aucun LLM synchrone dans le hot path (< ~200 ms, §7).
- Decision Log append-only : jamais d'UPDATE/DELETE, l'état est une projection.
- **Une feature par commit.**

## Sortie
Tranche fonctionnelle, Definition of Done OK (`/done`), essai manuel concluant, dépôt vert.

## Enchaînement
`/feature` → `/devil` (revue critique) → `/polish` (ergonomie) → `/done` → `/commit`.
Si l'UI évolue, passer d'abord par `/design` (Loop 6).
