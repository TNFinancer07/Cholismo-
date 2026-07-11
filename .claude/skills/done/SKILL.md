---
name: done
description: Vérifier la Definition of Done avant de clôturer une tâche du terminal Cholismo. À utiliser en fin de Loop 1/2/3, avant /commit. N'affirme jamais « fait » si une étape n'a pas réellement été exécutée.
---

# /done — transverse · Definition of Done

Verdict clair **DONE** ou **PAS DONE** + ce qui bloque. Honnêteté d'abord.

## Checklist
1. **Build / démarrage** — backend démarre, front build (`tsc` + `vite build`) sans erreur.
2. **Tests verts** — pytest (backend) et tests front pertinents passent.
3. **Lint vert** — lint/typecheck OK.
4. **Essai manuel** — le flux réel a été exercé (pas seulement les tests) ; pour une surface UI, capture à l'appui.
5. **Diff atomique** — un seul sujet, traçable au schéma / à la spec.
6. **Contraintes dures (§2)** — aucun ordre passé, append-only respecté, Phase 0 déterministe, fail-closed, pas de LLM synchrone dans le hot path.

## Sortie
Verdict explicite : **DONE** (toutes cases cochées) ou **PAS DONE** + liste précise de ce qui manque.

## Garde-fou
**Ne jamais affirmer « fait »** si une étape n'a pas été réellement exécutée. Un test non lancé n'est pas un test vert.
