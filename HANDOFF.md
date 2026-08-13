# HANDOFF — état du dépôt, branche `claude/cholismo-v2-terminal-dev-l9qtlu`

> Passation. Ce document dit **ce qui est prouvé, ce qui ne l'est pas, et ce qui reste à faire**
> — dans cet ordre, parce que c'est l'ordre dans lequel on se trompe.
>
> Une seule règle de lecture : **rien ici n'affirme que la stratégie fonctionne.** Le taux de
> réussite du LSR est **inconnu**. Tout ce qui a été construit sert à le *mesurer*, jamais à le
> confirmer.

Dernier commit : `ded7c58` (D-091) · 69 commits sur la branche · 82 décisions dans `DECISIONS.md`.

---

## 1. Ce qui est prouvé

Prouvé = **exécuté**, avec un résultat observé. Pas « écrit et relu ».

| Brique | Preuve |
|---|---|
| Backend (52 modules, ~21 800 lignes) | **1747 tests verts**, `ruff` clean |
| Suite de tests (77 fichiers, ~19 600 lignes) | ratio test/code ≈ 0,9 |
| Contrat de boucle + superviseur (D-073) | une boucle morte n'en tue aucune autre — observé en réel (D-075) |
| Pont Options L2 + 3ᵉ canal SSE `options` (D-074/075) | appelé en réel (`curl`), contexte `STALE` observé worker arrêté |
| Portage O1-O5 + **verrou de parité D-072** | des tests Python **lisent le TypeScript** et échouent s'il diverge |
| Rejeu MBO (carnet L2/L3, actions A/C/M/T/F/R) | horodatages **entiers ns**, prix point fixe 1e-9 |
| Simulateur FIFO (D-078/081) | 4 défauts de l'artefact corrigés, dont le fill-au-touché |
| Journal des setups + matrice de calibration (D-082) | append-only, **triggers SQLite** refusant `UPDATE`/`DELETE` |
| Détecteur LSR microstructurel pur (D-087) | armement sur sweep MBO, news en **filtre aval**, plus en prérequis |
| Briques de production (D-091) | verdict opérationnel, template, manuel |

**Les garanties structurelles** (ce sont elles qui tiennent le système, pas les tests) :

- **§2.1 — aucun ordre.** Aucun module ne parle à un courtier. Deux tests de garde refusent
  `broker`, `submit_order`, `requests`, `httpx`, `socket`, `aiohttp` dans la source
  d'`execution_sim` et de `replay_harness`. Les identifiants courtier sont **volontairement
  absents** de `.env.production.example`, avec le refus écrit en tête du fichier.
- **Mode G2 consultatif, par construction.** Aucun évaluateur O1-O5 ne retourne de booléen,
  aucun ne lève, l'entrée de journal n'a ni `blocked` ni `allowed`. Il n'existe **aucun chemin de
  blocage à désactiver** — d'où le chapitre volontairement vide du manuel.
- **Append-only imposé par le moteur**, pas par convention. La décision est immuable ; l'issue est
  un **event ultérieur** qui la référence ; l'état courant est une **projection**.
- **Fail-closed.** `None` n'est jamais `0`. Une donnée absente s'affiche `—`, jamais une dernière
  valeur figée.

---

## 2. Ce qui n'est PAS prouvé

C'est la section qui compte. La lire avant de reprendre.

### 2.1 La maquette v17 n'a jamais été ouverte dans un navigateur

> **Correction (D-092).** Une version antérieure de cette section affirmait que le frontend était
> invérifiable — « `vitest` et `tsc` absents, npm hors ligne ». **C'était faux, et c'était ma
> faute** : j'avais lancé les commandes de constat sans ancrer leur répertoire, et lu leur réponse
> comme un fait. `frontend/src/` a **9 fichiers de test / 125 tests** et un `tsc --noEmit` en mode
> `strict` sur ses **81 fichiers** — les deux verts, et désormais dans la CI.
>
> Ce qui suit est ce qui reste réellement non prouvé, une fois l'erreur retirée.

`frontend/public/v17/` (`index.html` + `live.js`) est validé par `node --check` — **la syntaxe,
pas le comportement**. Vérifié : la maquette n'est atteinte **ni par `tsc`** (hors de
`include: ["src"]`) **ni par aucun des 9 fichiers de test**. C'est du HTML/JS statique vendu, et
aucun rendu n'a été observé.

Le point le plus fragile est nommé dans `docs/p4-verification.md` §1 : `live.js` insère son
bandeau **après** `header.topbar`, sélecteur **déduit de la lecture du HTML, pas observé**. S'il
rend `null`, `ensureStrip()` abandonne et **tout le rendu s'arrête**. Correction d'une ligne — mais
il faut d'abord ouvrir la page.

> Contexte utile au repreneur : c'est exactement là que je me suis trompé en D-090. J'avais
> **déduit** une cartographie d'identifiants au lieu de la **lire** ; `#p6` était la section
> entière de l'onglet Backtest, qu'un `innerHTML` aurait rasée. Le correctif porte sur la
> méthode — `live.js` n'écrit plus que dans ses propres conteneurs `#cho-*` (plus `#px`).

### 2.2 Aucune donnée réelle n'a traversé la chaîne de calibration

L'infrastructure P2 est complète et testée. Elle n'a **jamais vu de séance réelle**.

- **Aucun setup ne s'est jamais armé en rejeu.** La cause est identifiée (D-087) : le générateur
  synthétique produit des barres dégénérées et 25 minutes d'historique là où l'ATR lent en exige
  ~50. C'est le **générateur** qui est en cause, pas la chaîne.
- **La matrice de calibration n'a jamais produit une seule cellule chiffrée** — tout est
  `INSUFFICIENT_DATA`, ce qui est son comportement correct sous échantillon nul.
- **La magnitude du biais de touché reste non chiffrée** depuis D-078. C'est *la* mesure que la
  phase existe pour produire : un backtest naïf l'affiche structurellement à 0 %.

J'ai refusé d'ajuster le générateur synthétique jusqu'à obtenir des armements — un générateur
réglé pour produire le résultat attendu mesure le générateur, pas la stratégie. **Seule une
séance MBO réelle ferme ce point.**

### 2.3 Les connecteurs de données live n'existent pas

`.env.production.example` porte `RITHMIC_*`, `THETADATA_API_KEY`, `UNUSUAL_WHALES_API_KEY` —
**marqués inertes, et ils le sont**. Aucun module ne les lit. `workers/options_worker.py` tourne
sur `MockVendorClient`. Renseigner une clé ne branche rien : il faut implémenter le `Protocol`
`OptionsVendorClient`. Le connecteur Rithmic n'existe pas (D-083).

### 2.4 Reste à porter du moteur TypeScript

F6 (cooldown après 2 pertes), F7-resubmit (900 s), F8 (campagne), A5b (confluence au 1ᵉʳ trade),
scale-out (clip 50 %), prix d'annulation. Les quatre premiers exigent un `LsrRuntimeState` qui
doit être une **projection du Decision Log** (§2.5), pas un champ mutable — c'est ce qui rend la
tranche non triviale.

Un test verrouille aussi le refus de brancher la gate ATR sur F3 : Cholismo n'a pas d'ATR à lui
donner, et le brancher rendrait le moteur définitivement muet. **Ce test échouera le jour où le
tampon suffira** — un refus qui s'auto-annule quand sa cause disparaît.

---

## 3. Les deux actions externes en attente

### A. Test navigateur

```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000
cd frontend && npm run dev        # puis http://localhost:5173/v17/
```

Suivre `docs/p4-verification.md`, **ordonné par risque décroissant**. Les trois points qui
comptent : le bandeau apparaît (§1), la maquette n'est pas abîmée (§2), et backend coupé →
les champs affichent `—` et non un zéro (§3).

### B. Passe de calibration sur MBO réel

```bash
# 1. contexte de séance (VIX + calendrier), horodaté au point-in-time
python -m app.mbo.build_context --from 2025-03-03 --to 2025-03-07 -o contexte.json

# 2. la chaîne complète : Parquet → carnet → armement → FIFO → issues → journal → matrice
python -m app.calibration seance.parquet --context contexte.json --csv setups.csv
```

Attendu : `MES`/`MNQ`, GLBX.MDP3, 09:30-11:30 ET. Ce que la passe rendra enfin mesurable —
le **taux de non-remplissage**, donc la magnitude du biais de touché.

**Ce qu'elle ne rendra pas** : un verdict sur la stratégie. Une séance donne un échantillon,
pas un taux de réussite. La matrice refusera de chiffrer une cellule sous `--min-sample`
(défaut 10), et c'est voulu.

---

## 4. Exploitation

- **`OPERATING_MANUAL.md`** — procédures d'urgence. Le réflexe : lire le `verdict` de
  `/loops/health` avant d'agir. `PARTIAL` est l'état **normal** aujourd'hui (`core.tick` est
  assurée par `engine.py`, pas encore migrée sous le contrat) ; le confondre avec `DEGRADED`
  ferait courir pour rien à chaque démarrage.
- **`.env.production.example`** — `cp` puis remplir. Tout défaut est le mode le plus sûr : un
  fichier vide démarre un terminal de démonstration, jamais un live à moitié configuré.
- **`DECISIONS.md`** — 82 entrées. Chaque arbitrage y est daté avec sa raison. En cas de doute
  sur « pourquoi c'est comme ça », la réponse y est.

## 5. Les trois pièges de ce dépôt

Écrits parce qu'ils m'ont eu, chacun au moins une fois :

1. **Une boucle morte ressemble à une boucle calme.** C'est la raison d'être du contrat de
   boucle. Un écran figé n'est pas un marché calme : vérifier `/loops/health`, pas l'écran.
2. **Supposer une structure au lieu de l'ouvrir.** Trois fois — le chemin du tape (D-077), le
   parseur de calendrier (D-085), la cartographie DOM (D-090) — l'essai réel a trouvé ce que les
   tests avaient manqué, parce que le test encodait la même supposition que le code.
3. **Un tableau vide est ambigu.** Un calendrier « chargé mais vide » non publié rendait tout
   armement impossible (D-086). `None` (illisible) et `[]` (vide) ne se confondent jamais.

---

*Dépôt vert. `main` est resté sur `b983097` (bootstrap) : cette branche n'a jamais été fusionnée, et
**aucune PR n'a été ouverte pour elle**. À savoir en reprenant : la PR #1 du dépôt est ouverte sur
une **autre** branche (`claude/finance-software-inspiration-88gdl9`, V1) et ne contient rien du
travail décrit ici.*
