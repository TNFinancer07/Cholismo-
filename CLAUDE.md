# CLAUDE.md — Cholismo Terminal (« The Builder »)

> Contexte racine pour Claude Code (Opus 4.8 / Fable 5).
> Lis-le **en entier** avant d'écrire du code. Puis exécute `TASKS.md` dans l'ordre, en te
> référant à `PRD.md`. Les artifacts existants sont dans `/reference/` — **extrais** d'eux,
> mais **uniquement ce qui est marqué `AUTORITÉ`** (voir §11). Ne canonise pas la maquette.

---

## 1. Ce qu'on construit

Un **terminal de trading full-stack** pour un système human-in-the-loop nommé **Cholismo**.
Cible : futures ES/NQ (microstructure) + EUR/USD (macro FX). Deux opérateurs en miroir.

Le terminal n'est **pas un dashboard**. C'est le **rendu visuel direct du `ContextSchema v1.0`**.

> **Un panneau = un bloc du schéma. Single source of truth.**
> Tout panneau non traçable à un champ du schéma **ne doit pas exister**.

**Objectif réel du projet** (ne jamais le perdre de vue) : passer en live = **50+ trades,
Sharpe positif, preuve comportementale**. Le terminal existe pour *servir* ça, pas l'inverse.
Priorité de build = §10. On construit depuis l'usage réel, pas la complétude a priori.

---

## 2. Contraintes architecturales dures (jamais violées)

1. **Aucune exécution automatique d'ordre.** Go/No-Go **enregistre** une décision, ne passe
   jamais d'ordre.
2. **Phase 0 est un moteur de règles DÉTERMINISTE**, inviolable à toutes les couches.
   Un LLM (Groq) peut être **advisory**, mais **le verrou est du code déterministe**
   (booléens de checklist), jamais un LLM non déterministe. Si Groq est down/lent →
   **fail-closed = BLOQUÉ**. L'UI reflète Phase 0, ne l'override jamais.
3. **No signal without data.** Chaque panneau définit son rendu **donnée périmée / absente**
   (voir §8). En absence de données → fail-closed, jamais une valeur inventée affichée comme réelle.
4. **Fail-closed par défaut.** Tout ROUGE sans action définie → `REQUEST_ACK`. Aucun trade
   sans ack humain explicite.
5. **Decision Log event-sourced, append-only.** Aucun `UPDATE`/`DELETE`. La décision est un
   event immuable ; l'outcome est un **event ultérieur** qui la référence ; l'« état courant »
   est une **projection** (grammaire Murex/Calypso réelle). Voir `PRD §Zone D`.
6. **Discipline dans l'infra, pas dans la volonté.**
7. **Process score ≠ result score.** Jamais consolidés ; result score affiché après 20+ trades.
   Le **Cortex Cognitif** (D-035) opérationnalise ce score de *processus* : sur les trades
   réconciliés, 3 biais **déterministes** — **FOMO** (durée courte sur anomalie de delta),
   **EXEC_TOO_LONG** (durée > seuil), **REVENGE** (< 3 min après une perte) — alimentent un
   **Psych-Score /100** (% de trades sans biais). **Advisory pur** : il annote, ne bloque ni ne
   modifie jamais l'exécution (§2.1) ; jamais consolidé avec le P&L (result). Règles + seuils :
   `DECISIONS.md` D-033/D-035.
8. **Claude n'est JAMAIS synchrone dans le hot path live.** Le chemin décision live est
   rapide et déterministe. Claude (scoring) et Gemini (audit) sont **périodiques/async**.
   Voir §7 budget latence.

---

## 3. Opérateurs et code couleur

| Profil | Domaine | Bloc | Couleur |
|---|---|---|---|
| **Sony (S1)** | Intraday microstructure, order flow, SVS v3.0, S1 mean reversion | `s1_state` | **ROUGE framboise** (D-024) |
| **Youssef (S2)** | Macro FX, matrice Bridgewater, cascade, EUR/USD | `s2_state` | **JAUNE citron** (D-024) |
| **Router** | Arbitrage / signal unifié | `unified_signal_output` | **OR (bordure/trait, pas remplissage)** |

Statuts risque : **VERT / JAUNE / ROUGE**. ⚠️ **Le risque n'est jamais encodé par la seule
couleur** : toujours **forme + icône + position** en plus (daltonisme rouge/vert ~8 % des
hommes). ⚠️ Les couleurs opérateur (rouge/jaune, arbitrage opérateur D-024) voisinent avec
les statuts de risque : leurs **teintes sont distinctes** (framboise ≠ rouge saumon du
risque ; citron ≠ ambre du risque ≠ or Router) et **chaque bloc porte un badge texte**
`S1 · SONY` / `S2 · YOUSSEF` / `ROUTER` / `SYSTÈME` (mixte : `S1 + S2`) — la couleur
opérateur n'est jamais seule. Dark-mode, densité maximale, monospace pour les chiffres.

---

## 4. Stack technique

**Frontend** — Vite + React + TS + Tailwind + shadcn/ui. Dark, monospace, **nav clavier first**.
Consommation temps réel **SSE segmenté par cadence** (voir §6).

**Backend** — FastAPI (REST + SSE). **Redis** (état intra-session, âges de donnée, countdowns).
**SQLite** (event store append-only + checkpointing).

**Orchestration** — n8n (workflows : streak, routing). LangGraph (graph-state, checkpointing
SQLite). Phase 0 déterministe appliquée **avant** tout appel Claude.

**IA** — Claude Opus 4.8 (scoring, **async/périodique**). Groq LLaMA 3.3 70B (advisory Phase 0).
Gemini 2.5 Pro (audit 20 trades, async).

**Données (démo)** — interface unique **`MarketDataSource` swappable**. `MockDataSource`
**doit injecter les pathologies réelles** : ticks manquants, données en retard, valeurs
contradictoires entre sources, NaN, désync d'horloge. Un mock trop propre est un piège. Le
stack tourne end-to-end sans feed live ; le mock est le seul point de couture.

---

## 5. Langue
UI **en français** ; code + commentaires + identifiants + champs du schéma **en anglais**.

---

## 6. Cadences & flux (le schéma est UN objet, pas UN flux)
Le single-source-of-truth est conceptuel, pas physique. Segmente en **canaux par cadence**,
events SSE **partiels par bloc** :
- **Canal rapide** (sous-seconde) : `s1_state`, `bridge_variables`.
- **Canal lent** (minutes+) : `s2_state`, `cascade`, `bridgewater_matrix`.
Ne jamais re-pousser la macro à chaque tick microstructure.

---

## 7. Budget latence / coût (à respecter dès la conception)
- **Hot path live** = déterministe, < ~200 ms. Zéro appel LLM synchrone dedans.
- **Groq Phase 0** : advisory, < 100 ms, fail-closed si timeout.
- **Claude scoring** : hors hot path, cadence + coût/session à borner et logger.
- **Gemini audit** : tous les 20 trades, async.

---

## 8. Les deux « inconnues » — traitées honnêtement (ne pas maquiller)
1. **`s2_macro_score` (A3)** : méthode NON validée. **Ne pas afficher un faux nombre autoritaire.**
   A3 s'affiche `NON CALIBRÉ` ; tant que non calibré, **le poids Macro (20 %) tombe à 0** et le
   signal unifié est marqué **dégradé**. La fonction `compute_s2_macro_score()` existe, isolée,
   commentée `v1 provisional — calibration owner: Youssef`, mais **ne contribue pas au live**
   avant validation. Voir `PRD §A3`.
2. **TTL GEX (B2)** : le moteur Greeks a une vitesse inconnue → **ne pas afficher un countdown
   fixe trompeur**. B2 affiche l'**âge réel de la donnée** (`now − last_gex_compute_ts`) et
   passe **STALE** au-delà d'un seuil. Pas de compte à rebours vers une péremption supposée.
   Voir `PRD §B2`.

---

## 9. Modèle de concurrence (tranché)
**Un opérateur par instance frontend, backend partagé.** Sony et Youssef ont chacun leur
instance ; le `sync_state` S1↔S2 se calcule côté backend partagé. Le self-check cognitif et le
Go/No-Go sont attribués à l'opérateur de l'instance (champ `operator` sur chaque event).
Pas de multi-user dans une même instance en v1.

---

## 10. Priorité de build — MVP impitoyable d'abord
Le scope complet est différable. **Ship d'abord le harnais de discipline minimal** qui permet
de prendre et prouver 50 trades disciplinés :
- **MVP (bloquant)** : ContextSchema + Phase 0 déterministe + affichage score unifié +
  Go/No-Go → Decision Log event-sourced + tracker calibration (C4) + **réconciliation
  NinjaTrader** (§`PRD §Réconciliation`).
- **Puis** : zones A/C complètes, console orchestrateur, vues de mode, onglet prompts.
- **En dernier** : n8n/LangGraph, heatmap Bridgewater, câblage IA complet.
`TASKS.md` est ordonné dans ce sens. Ne construis pas la phase N+1 avant que N tourne.

---

## 11. Autorité des sources `/reference/`
Les artifacts `/reference/` sont des **maquettes** : arbres conditionnels et formules souvent
**inventés** (Q7/Q8 jamais résolues). N'extrais que les blocs marqués `AUTORITÉ` dans
`/reference/MANIFEST.md`. Tout le reste est `PLACEHOLDER` : t'en inspirer pour l'UI, **jamais**
comme logique métier canonique. En cas de doute → `PLACEHOLDER`, et consigne dans `DECISIONS.md`.

---

## 12. Méthode de travail
Suis `TASKS.md` dans l'ordre, commit atomique par tâche. Un panneau = un composant lisant **un**
champ du schéma. Isole toute formule non figée (`v1 provisional`). Ne pose de question que sur
contradiction réelle de spec ; sinon applique et note l'hypothèse dans `DECISIONS.md`.

---

## 13. Systèmes de loop — DÉVELOPPEMENT

> Ces boucles **opérationnalisent la §12** (méthode de travail) ; leurs garde-fous héritent de la
> **§2** (contraintes dures). Le principe design « inspiré, jamais copié » guide la Loop 6.
> Les boucles d'exécution *dans* le terminal sont décrites dans **`RUNTIME_LOOPS.md`**.
> Chaque boucle est aussi câblée à une skill Claude Code (`.claude/skills/`).

**Contrat commun : Déclencheur → Étapes → Condition de sortie → Garde-fous.**
On répète jusqu'à la condition de sortie. 3 itérations sans progrès mesurable → on **stoppe et on
remonte le blocage** (pas de brute-force).

### Loop 0 — Décision de stack — ✅ RÉSOLU (voir §4)
Le stack est figé (§4 : FastAPI + Pydantic v2 + Redis + SSE + SQLite / React + TS + Vite + Tailwind
+ zustand / LangGraph + n8n). Boucle conservée pour mémoire ; à ne rejouer qu'en cas de remise en
cause majeure, avec un ADR dans `docs/adr/`.

### Loop 1 — Développement de feature  ·  skill `/feature`
1. **Clarifier** — 1 phrase + cas limites, avant de coder. Ambigu → question (cf. §12).
2. **Plan** — plus petite tranche livrable ; décris l'interface publique (un panneau = un champ du schéma).
3. **Test d'abord** — au moins un test qui échoue et décrit le comportement voulu.
4. **Implémenter** — le minimum pour passer au vert.
5. **Auto-revue** — relis le diff comme celui d'un inconnu.
6. **Vérifier** — tests + lint + essai manuel réel.
7. **Commit** — atomique (§12), dépôt vert.
- **Sortie** : tranche fonctionnelle, DoD ok, essai manuel concluant. **Garde-fou** : une feature par commit.

### Loop 2 — Correction de bug  ·  skill `/bugfix`
1. **Reproduire** (suite d'actions minimale — pas de fix sans repro). 2. **Capturer** par un test de
régression. 3. **Isoler** la cause racine, pas le symptôme. 4. **Corriger** ciblé. 5. **Confirmer**
(régression + tests verts). 6. **Prévenir** (où ailleurs ce bug ?).
- **Sortie** : repro impossible, régression verte, rien d'autre cassé. **Garde-fou** : jamais masquer le symptôme.

### Loop 3 — Refactor sûr  ·  skill `/refactor`
1. **Filet de tests** couvrant l'existant d'abord. 2. **Micro-étapes**, verts entre chaque.
3. **Zéro changement de comportement**. 4. **Commit fréquent**.
- **Sortie** : code plus clair, comportement identique prouvé. **Garde-fou** : jamais refactor + feature ensemble.

### Loop 4 — Devil's advocate  ·  skill `/devil`
1. **Attaquer** : 3 façons de casser (entrée vide/énorme, saisie invalide, coupure du flux marché,
terminal redimensionné, Ctrl-C au mauvais moment). 2. **Cas limite oublié** (état partagé, ordre,
ressource non libérée). 3. **Questionner le design** (plus simple ?). 4. **Intégrer** / documenter les risques.
- **Sortie** : 3 scénarios gérés ou documentés hors-scope. **Garde-fou** : revue honnête, jamais complaisante.

### Loop 5 — Polish UX  ·  skill `/polish`
1. **Latence perçue** : feedback < 100 ms (cohérent §7). 2. **Messages** lisibles/actionnables.
3. **Cohérence** (raccourcis, vocabulaire, code couleur §3). 4. **Sortie propre** (Ctrl-C, quit).
5. **Découvrabilité** (help / ?).
- **Sortie** : utilisateur sans doc comprend, jamais bloqué sans message. **Garde-fou** : lisibilité > décoration.

### Loop 6 — Langage visuel & inspiration  ·  skill `/design`  ·  « inspiré, jamais copié »
1. **Extraire les principes, pas les pixels** des terminaux financiers (densité, clavier-first,
latence faible, layout tabulaire monospace, couleur sémantique, panneaux composables).
2. **Traduire en identité propre** (design tokens, nomenclature de commandes maison).
3. **Checklist anti-copie** : pas de charte signature reprise, pas de codes propriétaires (`<GO>`),
pas de layout/logo/nom identifiable → doute = on s'éloigne.
4. **Documenter** `docs/design-language.md`.
- **Sortie** : design distinctement cholismo, chaque emprunt justifié. **Garde-fou** : l'IDÉE, jamais l'EXPRESSION protégée.

### Enchaînement
```
Loop 0 (résolu) → Loop 6 (design, à l'évolution UI)
                         │
   ┌────► Loop 1 (feature) ─► Loop 4 (revue) ─► Loop 5 (polish) ─► /done ─► /commit
   │            Loop 2 (bug) ─┤
   │            Loop 3 (refactor) ─┘
   └── par jalon (§10) — dépôt toujours vert entre deux loops ───────
```

### Skills transverses (`.claude/skills/`)
`/loop-check` audite les boucles runtime (`engine.py`, `ai/tasks.py`…) contre les pièges de
`RUNTIME_LOOPS.md` · `/done` vérifie la Definition of Done · `/commit` produit un commit atomique.

### Voir aussi
- **`RUNTIME_LOOPS.md`** — boucles d'exécution du terminal (principale, rendu, input, données, retry, watchdog, arrêt gracieux).
- **`.claude/skills/`** — une skill par loop, invocables via `/nom`.
