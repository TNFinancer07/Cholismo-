# HANDOFF — état du dépôt, branche `claude/cholismo-v2-terminal-dev-l9qtlu`

> Passation. Ce document dit **ce qui est prouvé, ce qui ne l'est pas, et ce qui reste à faire**
> — dans cet ordre, parce que c'est l'ordre dans lequel on se trompe.
>
> Une seule règle de lecture : **rien ici n'affirme que la stratégie fonctionne.** Le taux de
> réussite du LSR est **inconnu**. Tout ce qui a été construit sert à le *mesurer*, jamais à le
> confirmer.

Dernier commit : `69b7d1e` (D-105) · 85 commits sur la branche · 96 décisions dans `DECISIONS.md`.
**CI verte** sur chaque push (`.github/workflows/ci.yml`, D-092) — le vert n'est plus une parole.

---

## 1. Ce qui est prouvé

Prouvé = **exécuté**, avec un résultat observé. Pas « écrit et relu ».

| Brique | Preuve |
|---|---|
| Backend (113 modules) | **1844 tests verts**, `ruff` + `mypy` clean — **rejoués en CI** |
| Frontend `src/` (40 panneaux) | **158 tests verts** + `tsc --noEmit` `strict` sur 81 fichiers — **rejoués en CI** |
| Suites de tests (83 fichiers backend, 11 frontend) | ratio test/code ≈ 0,9 |
| Dépendances verrouillées (D-092) | `requirements.lock` + `package-lock.json` — un rouge désigne le code, pas le calendrier |
| Contrat de boucle + superviseur (D-073) | une boucle morte n'en tue aucune autre — observé en réel (D-075) |
| Pont Options L2 + 3ᵉ canal SSE `options` (D-074/075) | appelé en réel (`curl`), contexte `STALE` observé worker arrêté |
| Portage O1-O5 + **verrou de parité D-072** | des tests Python **lisent le TypeScript** et échouent s'il diverge |
| Rejeu MBO (carnet L2/L3, actions A/C/M/T/F/R) | horodatages **entiers ns**, prix point fixe 1e-9 |
| Simulateur FIFO (D-078/081) | 4 défauts de l'artefact corrigés, dont le fill-au-touché |
| Journal des setups + matrice de calibration (D-082) | append-only, **triggers SQLite** refusant `UPDATE`/`DELETE` |
| Détecteur LSR microstructurel pur (D-087) | armement sur sweep MBO, news en **filtre aval**, plus en prérequis |
| Briques de production (D-091) | verdict opérationnel, template, manuel |
| Règles de protection F6/F7 (D-094→096) | état d'exécution en **projection** du journal, actives dans `engine.py` |
| Réconciliation d'entrée automatique (D-098) | un fill NT8 observé devient un `ReconEvent` — plus d'import CSV pour l'entrée |
| Couture microstructure live (D-097) | `MicrostructureClient`, fail-closed sans repli sur le mock |
| Codec Tradovate (D-100) | trames, quotes→prints, DOM→carnet, fills→réconciliation |
| Seuils OF dynamiques (D-101) | publiés par le moteur, **B2 directionnel**, rien en dur à l'écran |
| Carte de sensibilité + biais du survivant (D-102/103) | `/analyses/resilience`, écran avec badge `HYPOTHÈSE` par cellule |

**Les garanties structurelles** (ce sont elles qui tiennent le système, pas les tests) :

- **§2.1 — aucun ordre.** Aucun module ne parle à un courtier. Deux tests de garde refusent
  `broker`, `submit_order`, `requests`, `httpx`, `socket`, `aiohttp` dans la source
  d'`execution_sim` et de `replay_harness`. **Un troisième garde couvre `tradovate.py`** (D-100) :
  l'API Tradovate SAIT passer des ordres, donc le module est borné explicitement plutôt que
  « pas encore écrit » — `placeorder`, `modifyorder`, `cancelorder`, `liquidateposition` sont
  refusés dans sa source. Les identifiants courtier sont **volontairement absents** de
  `.env.production.example`, avec le refus écrit en tête du fichier.
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
> comme un fait. `frontend/src/` a **11 fichiers de test / 158 tests** et un `tsc --noEmit` en mode
> `strict` sur ses **81 fichiers** — les deux verts, et dans la CI depuis D-092.
>
> Ce qui suit est ce qui reste réellement non prouvé, une fois l'erreur retirée.

`frontend/public/v17/` (`index.html` + `live.js`) est validé par `node --check` — **la syntaxe,
pas le comportement**. Vérifié : la maquette n'est atteinte **ni par `tsc`** (hors de
`include: ["src"]`) **ni par aucun des 11 fichiers de test**. C'est du HTML/JS statique vendu, et
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

### 2.3 Aucun connecteur live n'est branché

La **couture** existe (`MicrostructureClient`, D-097) et le **codec Tradovate** aussi (D-100) —
mais `CLIENTS` est **vide** et le **transport n'est pas écrit** : sans identifiants ni accès au
service, l'écrire produirait du code d'apparence fonctionnelle que personne n'a vu tourner.

⚠️ Les libellés d'endpoints et la forme des trames du codec viennent de la **documentation
publique** et **n'ont été confrontés à aucun service réel**. Ce qui est garanti est la cohérence
interne et le fail-closed, pas la conformité au protocole.

La plateforme cible est **Tradovate** (le choix a changé en cours de route : Rithmic n'est plus
visé). `.env.production.example` porte encore `RITHMIC_*`, `THETADATA_API_KEY`,
`UNUSUAL_WHALES_API_KEY` — **inertes, et ils le disent**. `workers/options_worker.py` tourne sur
`MockVendorClient` : renseigner une clé ne branche rien, il faut implémenter le `Protocol`.

Sans connecteur, le terminal démarre en mode simulé **et l'annonce** (D-093) — toute lecture est
estampillée `mock:*` et ne peut pas se faire passer pour une mesure.

### 2.4 Reste à porter du moteur TypeScript

**Portés depuis** : F6 (cooldown), F7 (FOMO + re-soumission), et le `LsrRuntimeState` — en
**projection** du Decision Log, jamais un champ mutable (D-094→096). Ils sont **actifs** dans le
chemin réel (`engine.py`), pas seulement disponibles.

**Restent** : F8 (campagne), scale-out (clip 50 %), prix d'annulation.

**A5b est bloqué en amont, pas par manque de temps.** Sa seconde condition,
`secondary_reference ∈ VAH|VAL|LVN`, n'a **aucun producteur** — vérifié : dans tout
`lsr-engine/src`, le champ est une *entrée*, jamais calculé. La définition métier est arrivée
(« proximité ≤ 2 ticks d'un niveau clé secondaire ») mais laisse ouvertes trois questions qui
changent le résultat : le niveau de **quelle séance** ? mesuré depuis le prix d'entrée ou depuis
le point de sweep ? que faire si **deux** niveaux qualifient ? Un test verrouille l'absence *et sa
raison*, et échouera le jour où un fichier du moteur calculera `secondaryReference`.

Un test verrouille aussi le refus de brancher la gate ATR sur F3 : Cholismo n'a pas d'ATR à lui
donner, et le brancher rendrait le moteur définitivement muet. **Ce test échouera le jour où le
tampon suffira** — un refus qui s'auto-annule quand sa cause disparaît.

---

## 3. Les trois actions externes en attente

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

### C. Transport Tradovate sur le compte démo

Les identifiants restent **hors du dépôt** — `.env.local` au déploiement :
`TRADOVATE_USER`, `TRADOVATE_PASS`, `TRADOVATE_APP_ID`, `TRADOVATE_APP_VERSION`,
`TRADOVATE_CID`, `TRADOVATE_SEC`, plus le symbole du contrat.

Ordre le plus utile pour valider : **authentification REST d'abord**, puis une souscription quote
sur **un seul contrat**. C'est là que la forme réelle des trames se vérifie — le codec est écrit
contre la doc, pas contre le service.

Une fois le transport écrit, enregistrer le client dans `CLIENTS` (`app/datasource/live.py`)
suffit à basculer le terminal en live : `LiveDataSource` refuse au démarrage si le nom du client
diverge de `MICROSTRUCTURE_SOURCE`, ce qui évite une coupure qui ne couperait rien.

---

## 4. Exploitation

- **`OPERATING_MANUAL.md`** — procédures d'urgence. Le réflexe : lire le `verdict` de
  `/loops/health` avant d'agir. `PARTIAL` est l'état **normal** aujourd'hui (`core.tick` est
  assurée par `engine.py`, pas encore migrée sous le contrat) ; le confondre avec `DEGRADED`
  ferait courir pour rien à chaque démarrage.
- **`.env.production.example`** — `cp` puis remplir. Tout défaut est le mode le plus sûr : un
  fichier vide démarre un terminal de démonstration, jamais un live à moitié configuré.
- **`DECISIONS.md`** — 96 entrées. Chaque arbitrage y est daté avec sa raison. En cas de doute
  sur « pourquoi c'est comme ça », la réponse y est.

## 5. Les pièges de ce dépôt

Écrits parce qu'ils m'ont eu, chacun au moins une fois :

1. **Une boucle morte ressemble à une boucle calme.** C'est la raison d'être du contrat de
   boucle. Un écran figé n'est pas un marché calme : vérifier `/loops/health`, pas l'écran.
2. **Supposer une structure au lieu de l'ouvrir.** Trois fois — le chemin du tape (D-077), le
   parseur de calendrier (D-085), la cartographie DOM (D-090) — l'essai réel a trouvé ce que les
   tests avaient manqué, parce que le test encodait la même supposition que le code.
3. **Un tableau vide est ambigu.** Un calendrier « chargé mais vide » non publié rendait tout
   armement impossible (D-086). `None` (illisible) et `[]` (vide) ne se confondent jamais.
4. **Le défaut se loge dans un zéro d'apparence anodine.** Deux fois de suite : `0.0` pour le coût
   du slippage signifiait « sous la résolution de la grille », pas « gratuit » (D-102) ; `0.0`
   pour le biais du survivant signifiait « rien n'a été exclu », pas « pas de biais » (D-103).
   Une absence de mesure n'est pas une mesure nulle — et un `0` ne le dit jamais tout seul.
5. **« Ça existe mais rien ne l'appelle. »** Trois fois : le garde branché sur un driver sans
   appelant (D-096), des panneaux hors du registre (D-099), une vue non routée (D-105). Le code
   était juste à chaque fois, et le câblage absent. C'est le défaut le moins visible du dépôt,
   parce que **tout est vert**.

---

*Dépôt vert, CI verte. `main` est resté sur `b983097` (bootstrap) : cette branche n'est pas
fusionnée. La **PR #2** la porte, ouverte et à jour. À ne pas confondre avec la **PR #1**, ouverte
sur une **autre** branche (`claude/finance-software-inspiration-88gdl9`, V1), qui ne contient rien
du travail décrit ici.*
