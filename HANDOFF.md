# HANDOFF — état du dépôt, branche `claude/cholismo-v2-terminal-dev-l9qtlu`

> Passation. Ce document dit **ce qui est prouvé, ce qui ne l'est pas, et ce qui reste à faire**
> — dans cet ordre, parce que c'est l'ordre dans lequel on se trompe.
>
> Une seule règle de lecture : **rien ici n'affirme que la stratégie fonctionne.** Le taux de
> réussite du LSR est **inconnu**. Tout ce qui a été construit sert à le *mesurer*, jamais à le
> confirmer.

Dernier commit de code : `4f79c45` (D-120) · **225 commits** sur la branche · **111 entrées** dans `DECISIONS.md`
(numérotées jusqu'à `D-120`). **CI verte** sur chaque push (`.github/workflows/ci.yml`, D-092) —
le vert n'est plus une parole.

**Volumétrie** : 118 modules Python (`backend/app/`) + 3 workers autonomes · 97 fichiers TS/TSX
(`frontend/src/`), dont 48 composants de panneaux (33 adressables par le registre) · 89 fichiers de
test backend, 17 frontend.

---

## 1. Ce qui est prouvé

Prouvé = **exécuté**, avec un résultat observé. Pas « écrit et relu ».

| Brique | Preuve |
|---|---|
| Backend (118 modules) | **1925 tests verts**, `ruff` + `mypy` clean — **rejoués en CI** |
| Frontend `src/` (48 panneaux) | **215 tests verts** + `tsc --noEmit` `strict` sur 97 fichiers — **rejoués en CI** |
| Suites de tests (89 fichiers backend, 17 frontend) | ratio test/code ≈ 0,9 |
| Dépendances verrouillées (D-092) | `requirements.lock` + `package-lock.json` — un rouge désigne le code, pas le calendrier |
| Suite frontend indépendante du shell (D-120) | `NODE_ENV=production` ne rend plus 151 tests rouges |
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
| Icebergs / churn par niveau (D-106) | ternaire `None`/`True`/`False` — « spoofing » est une intention, pas une mesure |
| Journal des features à l'armement (D-108) | la valeur **réelle** du moteur, jamais une valeur théorique |
| Baseline R:R rendue explicite (D-109/110) | `model.rr` + provenance + **dispersion** observée (min/max, pas la moyenne seule) |
| Détecteur de vide de liquidité (D-111) | référence **glissante**, `None` sous 20 observations |
| Câblage D-106/D-111 (D-112) | chacun là où sa donnée existe : vide → moteur, icebergs → rejeu |
| Verrou F6/F7 à l'écran (D-113) | event SSE `protection_reject`, `GET /protection`, panneau **C6** |
| Alertes sonores (D-114/115) | `PLAYED`/`THROTTLED`/`UNAVAILABLE`, muet par défaut, indicateur permanent |
| Fenêtres détachées (D-116/117) | **un seul** flux SSE, 4 états de synchro, popup bloquée **dite** |
| Export Notion (D-118) | worker autonome, opt-in strict, champ absent **omis** (jamais un 0) |
| Pont Stream Deck (D-119) | 4 actions **réversibles**, `127.0.0.1`, lecture seule sur l'API |

**Les garanties structurelles** (ce sont elles qui tiennent le système, pas les tests) :

- **§2.1 — aucun ordre.** Aucun module ne parle à un courtier. Deux tests de garde refusent
  `broker`, `submit_order`, `requests`, `httpx`, `socket`, `aiohttp` dans la source
  d'`execution_sim` et de `replay_harness`. **Un troisième garde couvre `tradovate.py`** (D-100) :
  l'API Tradovate SAIT passer des ordres, donc le module est borné explicitement plutôt que
  « pas encore écrit » — `placeorder`, `modifyorder`, `cancelorder`, `liquidateposition` sont
  refusés dans sa source. **Un quatrième borne le pont Stream Deck** (D-119) : liste blanche de
  quatre actions d'interface, `decision_go` / `decision_no_go` / `place_order` / `arm_setup`
  **nommés comme refusés** plutôt qu'omis. Les identifiants courtier sont **volontairement absents**
  de `.env.production.example`, avec le refus écrit en tête du fichier.
- **Mode G2 consultatif, par construction.** Aucun évaluateur O1-O5 ne retourne de booléen,
  aucun ne lève, l'entrée de journal n'a ni `blocked` ni `allowed`. Il n'existe **aucun chemin de
  blocage à désactiver** — d'où le chapitre volontairement vide du manuel.
- **Append-only imposé par le moteur**, pas par convention. La décision est immuable ; l'issue est
  un **event ultérieur** qui la référence ; l'état courant est une **projection**.
- **Fail-closed.** `None` n'est jamais `0`. Une donnée absente s'affiche `—`, jamais une dernière
  valeur figée. La règle tient jusqu'aux couches périphériques : une propriété Notion absente est
  **omise** (D-118), une tuile Stream Deck sans mesure est `UNKNOWN` et non verte (D-119), un son
  ne se déclenche jamais sur une valeur `STALE` (D-114).

---

## 2. Ce qui n'est PAS prouvé

C'est la section qui compte. La lire avant de reprendre.

### 2.1 La maquette v17 n'a jamais été ouverte dans un navigateur

> **Correction (D-092).** Une version antérieure de cette section affirmait que le frontend était
> invérifiable — « `vitest` et `tsc` absents, npm hors ligne ». **C'était faux, et c'était ma
> faute** : j'avais lancé les commandes de constat sans ancrer leur répertoire, et lu leur réponse
> comme un fait. `frontend/src/` a **17 fichiers de test / 215 tests** et un `tsc --noEmit` en mode
> `strict` sur ses **97 fichiers** — les deux verts, et dans la CI depuis D-092.
>
> Ce qui suit est ce qui reste réellement non prouvé, une fois l'erreur retirée.

`frontend/public/v17/` (`index.html` + `live.js`) est validé par `node --check` — **la syntaxe,
pas le comportement**. Vérifié : la maquette n'est atteinte **ni par `tsc`** (hors de
`include: ["src"]`) **ni par aucun des 17 fichiers de test**. C'est du HTML/JS statique vendu, et
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
- **Le journal des features (D-108) est vide.** Son premier consommateur — `observed_rr()` — rend
  donc `INSUFFICIENT_DATA`, et c'est le comportement correct. Mais toute la roadmap « modèle »
  (§4, V3-13) s'appuie sur ce journal : **zéro ligne aujourd'hui**.
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
chemin réel (`engine.py`), pas seulement disponibles, et **visibles à l'écran** depuis D-113.

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

### 2.5 Les briques d'ergonomie n'ont jamais rencontré leur matériel

Toutes testées, **aucune éprouvée sur son support réel** — et le test simule précisément la partie
qui pourrait mentir :

| Brique | Ce qui est testé | Ce qui ne l'est pas |
|---|---|---|
| Fenêtres détachées (D-116/117) | logique de synchro, 4 états, popup refusée | `window.open` est **simulé** — aucune seconde fenêtre réelle, aucun rendu multi-écran |
| Alertes sonores (D-114/115) | la **règle** (`decideCues`), pure et déterministe | l'`AudioContext` réel — jsdom n'en fournit pas |
| Export Notion (D-118) | le **mappage**, pur et hors ligne | la conformité à l'API Notion — aucun appel réel |
| Pont Stream Deck (D-119) | projection, liste blanche, gardes réseau | aucun matériel branché, protocole Elgato non confronté |

C'est la même honnêteté que §2.1 : **« scellé et testé » et « éprouvé » ne sont pas le même mot.**

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

## 4. Roadmap Futur — Optimisations V3

Quinze chantiers, dans la numérotation d'origine. **Aucun n'est commencé.** Chacun porte son
**prérequis réel** : ce document a assez menti par omission pour qu'on n'ouvre pas une roadmap sans
dire ce qui manque avant de pouvoir la tenir.

Deux constats valent pour l'ensemble, et il faut les lire d'abord :

1. **Rien n'a été profilé.** Le hot path n'a jamais tourné sous charge réelle. Optimiser une
   latence non mesurée, c'est deviner — et c'est le contraire de la méthode du dépôt.
2. **Il n'y a aucun trade.** Tout ce qui apprend, calibre ou évalue le comportement (V3-08, 12, 13)
   attend un échantillon qui n'existe pas. Un modèle entraîné sur zéro ligne mémoriserait du bruit.

### Bloc I — Latence & mémoire (V3-01 → V3-03)

| # | Chantier | Prérequis bloquant |
|---|---|---|
| **01** | **Bus ZeroMQ / Shared Memory** — transport sub-ms entre processus | **Un profil.** Le SSE actuel n'a jamais été mesuré sous charge : on ignore s'il est le goulot |
| **02** | **Ring buffers pré-alloués** — zéro allocation, zéro GC dans la boucle chaude | Idem. Et un budget mémoire fixé : un ring mal dimensionné **perd des ticks en silence** |
| **03** | **Circuit breaker & fallback flux réseau** — dégradation contrôlée à la coupure | Un connecteur live (§3.C). Aujourd'hui il n'y a **aucun flux réel** à couper |

⚠️ **V3-03 doit hériter du fail-closed, pas l'assouplir.** Un « fallback » qui bascule sur une
source dégradée *sans le dire* recréerait exactement le défaut que D-093 a corrigé. La règle : un
repli s'annonce, il ne se substitue pas.

### Bloc II — Microstructure avancée (V3-04, 05, 06, 11)

| # | Chantier | Où ça s'accroche |
|---|---|---|
| **04** | **MBO Speed of Tape & Acceleration Index** | Le tape MBO existe en rejeu. Manque : la **normalisation** — une vitesse absolue ne veut rien dire entre MES et MNQ, même écueil que D-111 |
| **05** | **Iceberg Reconstruction Engine (tracking L3)** | **D-106 est le plancher déjà posé** : compteurs `added`/`traded` par niveau, ratio ternaire. La *reconstruction* (suivre un ordre entre ses réapparitions) est le cran au-dessus, et demande du MBO réel |
| **06** | **CVD Divergence Radar sur extrema** | `CvdStratifiedPanel` existe. Manque : une définition **testable** d'un extremum — sans elle, le radar signalera ce qu'on aura décidé qu'il signale |
| **11** | **L3/MBO Anomaly Engine** (iceberg, TWAP/VWAP, spoofing) | ⚠️ **D-106 a déjà tranché le nommage** : « spoofing » est une **intention**, pas une mesure. Le moteur doit publier `churn` / `cancel_ratio` et laisser la qualification à l'humain. Un champ nommé `spoofing` transformerait une observation en accusation |

### Bloc III — Risque & exécution (V3-07, 12, 14)

| # | Chantier | Statut honnête |
|---|---|---|
| **07** | **Dynamic position sizing (risque $ fixe / ATR)** | ⚠️ **Casse la baseline.** Toute la carte de résilience (D-102/109) suppose un **R constant**. Un sizing variable rend `_ruin_probability` faux tel quel — il faudra refaire la surface avant, pas après. Et Cholismo **n'a pas d'ATR** (§2.4) |
| **12** | **VaR intraday & stress tests Monte Carlo** | La machinerie Monte-Carlo **existe** (`resilience.py`). Manque la seule chose qui compte : une **série de P&L réelle**. Une VaR calculée sur une distribution supposée mesure la supposition |
| **14** | **SOR & algos d'exécution passifs** (post-only, volatility stops) | 🛑 **Conflit direct avec `CLAUDE.md` §2.1.** Ce n'est **pas une feature** : router et placer des ordres change la nature du système — d'observateur à acteur. Cela relève d'un **ADR** (`docs/adr/`) explicitement décidé et daté, jamais d'une tranche de développement. En l'état, quatre tests de garde le refusent structurellement, et c'est voulu |

### Bloc IV — Comportement & revue (V3-08, 10)

- **V3-08 — Détecteur de tilt comportemental (cadence d'interaction).** Le socle existe : le
  **Cortex Cognitif** (D-033/035) calcule déjà trois biais déterministes (FOMO, `EXEC_TOO_LONG`,
  REVENGE) et F6/F7 verrouillent (D-094→096, visibles depuis D-113). Le neuf est la **cadence
  d'interaction** — clics, allers-retours, hésitations.
  ⚠️ Deux règles héritées, non négociables : **advisory pur** (`CLAUDE §2.7` — il annote, ne bloque
  jamais), et **le terminal se met à observer son opérateur**. Ce second point est une décision de
  conception à écrire dans `DECISIONS.md` avant la première ligne de code, pas un effet de bord.

- **V3-10 — Auto-bookmark replay 30 s post-trade & analytics.** Le plus proche d'être faisable :
  le harnais de rejeu et le journal append-only existent tous les deux. Manque un **tampon
  circulaire** du tape (donc V3-02) et une règle de rétention. Valeur réelle : c'est la seule
  optimisation de cette liste qui **fabrique de la preuve** au lieu de la consommer — elle sert
  directement l'objectif des 50 trades.

### Bloc V — Visualisation (V3-09)

**V3-09 — DOM Heatmap Timeline 3D.** Spécifications retenues pour la conception du composant
(`LiquidityHeatmapPanel` est le point d'accroche existant) :

- **Rendu WebGL, ou Canvas 2D dans un Web Worker via `OffscreenCanvas`** — 60 FPS sans jamais
  bloquer le thread UI. C'est la contrainte structurante : un rendu qui fige l'interface pendant
  qu'il dessine transforme un outil de lecture en obstacle.
- **Accélération GPU et mémoire sans fuite au défilement temporel.** Le scroll dans l'historique est
  le cas qui fuit : chaque frame retenue est de la mémoire qui ne revient pas.
- **Palettes thermiques haute lisibilité** — *Dark Mode Pro* : bleu nuit → cyan → jaune → blanc
  incandescent.
  ⚠️ `CLAUDE §3` : **le risque n'est jamais encodé par la seule couleur.** Une rampe thermique est
  un dégradé continu — donc **inutilisable seule** pour un verdict. Elle porte l'**intensité**
  (volume), jamais le statut ; tout jugement garde forme + icône + position.
- **Bascule 2D / perspective 3D**, relief en Z pondéré par le volume.
- **Curseur filtre de bruit** : seuil de volume minimal, pour faire ressortir les blocs
  institutionnels.
  ⚠️ Un filtre **cache** des données. L'écran doit afficher le seuil actif en permanence — un
  carnet filtré qui ne dit pas qu'il l'est se lit comme un carnet vide, et « vide » est justement le
  signal de V3-11.
- **Distinction visuelle ajout / exécution / annulation** — c'est ce qui rend layering et churn
  lisibles. Les compteurs existent déjà par niveau (D-106) ; ici c'est leur rendu.
  ⚠️ Même règle qu'en V3-11 : on montre `added` / `traded` / `cancelled`, on n'étiquette pas
  « spoofing ».
- **Transparence temporelle dynamique** (fading) sur les zones passées.
  ⚠️ Un fading ne doit **jamais** être le seul indicateur de péremption : une donnée `STALE` reste
  `STALE` explicitement, elle ne se contente pas de pâlir.

### Bloc VI — Modèle & multi-actifs (V3-13, 15)

- **V3-13 — Machine Learning Microstructure Engine** (scoring via le feature store V3-11 / D-108).
  L'infrastructure d'enregistrement **existe** (D-108, journal append-only des features à
  l'armement). Elle contient **zéro ligne**.
  ⚠️ Deux verrous à poser **avant** d'écrire le premier `fit()` : la **taille d'échantillon
  minimale** se décide avant de voir les données, pas après ; et le score reste **advisory** —
  Phase 0 est un moteur déterministe (`CLAUDE §2.2`), un modèle ne peut pas ouvrir un verrou.
  Rappel de D-118 : une gate non mesurable est **omise** et non « refusée », sinon le modèle
  apprendrait qu'une absence de mesure prédit un refus.

- **V3-15 — Cointégration & radar de corrélation multi-actifs.** Demande un **second flux
  instrument** et un historique long. Aujourd'hui la chaîne est mono-instrument de bout en bout.
  ⚠️ Une cointégration mesurée sur une fenêtre courte se **rompt** hors échantillon : la fenêtre et
  le test de stabilité font partie de la spécification, pas du réglage.

### Vision d'ensemble

L'ordre utile n'est pas l'ordre de la liste. **V3-10** (bookmark post-trade) est le seul chantier
qui produit de la preuve plutôt qu'en consommer — il sert directement les 50 trades. Tout le
Bloc I attend un profil ; tout le Bloc VI attend un échantillon ; **V3-14 n'est pas un chantier
mais une décision** sur la nature du système.

Et l'objectif n'a pas changé (`CLAUDE §1`) : **50 trades, Sharpe positif, preuve
comportementale.** Aucune de ces quinze optimisations ne rapproche de ce but tant qu'une séance
réelle n'a pas traversé la chaîne. Le terminal sert la preuve — il ne la remplace pas.

---

## 5. Exploitation

- **`OPERATING_MANUAL.md`** — procédures d'urgence. Le réflexe : lire le `verdict` de
  `/loops/health` avant d'agir. `PARTIAL` est l'état **normal** aujourd'hui (`core.tick` est
  assurée par `engine.py`, pas encore migrée sous le contrat) ; le confondre avec `DEGRADED`
  ferait courir pour rien à chaque démarrage.
- **`.env.production.example`** — `cp` puis remplir. Tout défaut est le mode le plus sûr : un
  fichier vide démarre un terminal de démonstration, jamais un live à moitié configuré.
- **Trois workers autonomes**, hors du terminal, chacun opt-in et sans effet sur le hot path :
  `options_worker.py` (mock aujourd'hui), `notion_exporter.py` (D-118), `streamdeck_bridge.py`
  (D-119). Aucun n'est requis pour que le terminal tourne.
- **`DECISIONS.md`** — 111 entrées. Chaque arbitrage y est daté avec sa raison. En cas de doute
  sur « pourquoi c'est comme ça », la réponse y est.
  ⚠️ Les entrées **D-110 → D-119 ont été rédigées a posteriori** (D-120) : dix décisions prises en
  commit, avec leur raison dans le message, mais absentes du registre. Leur contenu est d'époque,
  leur écriture ne l'est pas.

## 6. Les pièges de ce dépôt

Écrits parce qu'ils m'ont eu, chacun au moins une fois :

1. **Une boucle morte ressemble à une boucle calme.** C'est la raison d'être du contrat de
   boucle. Un écran figé n'est pas un marché calme : vérifier `/loops/health`, pas l'écran.
   Transposé à l'écran en D-116 : une fenêtre détachée désynchronisée affiche des chiffres
   parfaitement lisibles qui ne décrivent plus rien.
2. **Supposer une structure au lieu de l'ouvrir.** Trois fois — le chemin du tape (D-077), le
   parseur de calendrier (D-085), la cartographie DOM (D-090) — l'essai réel a trouvé ce que les
   tests avaient manqué, parce que le test encodait la même supposition que le code.
3. **Un tableau vide est ambigu.** Un calendrier « chargé mais vide » non publié rendait tout
   armement impossible (D-086). `None` (illisible) et `[]` (vide) ne se confondent jamais.
4. **Le défaut se loge dans un zéro d'apparence anodine.** Trois fois : `0.0` pour le coût du
   slippage signifiait « sous la résolution de la grille », pas « gratuit » (D-102) ; `0.0` pour le
   biais du survivant signifiait « rien n'a été exclu », pas « pas de biais » (D-103) ; une
   propriété Notion à `0` aurait été indiscernable d'une mesure nulle (D-118). Une absence de mesure
   n'est pas une mesure nulle — et un `0` ne le dit jamais tout seul.
5. **« Ça existe mais rien ne l'appelle. »** Cinq fois : le garde branché sur un driver sans
   appelant (D-096), des panneaux hors du registre (D-099), une vue non routée (D-105), puis
   **deux modules justes et appelés par personne** (D-106 et D-111, câblés en D-112). Le code était
   juste à chaque fois, et le câblage absent. C'est le défaut le moins visible du dépôt, parce que
   **tout est vert**.
6. **Un calcul honnête dont l'écran aplatit la nuance.** D-110 : le JSON portait sa baseline R:R,
   la grille l'affichait sans la dire. D-113 : les verrous étaient actifs, l'écran muet — l'opérateur
   ne distinguait pas « aucun signal » de « signal écarté ». Le calcul juste ne suffit pas ; ce qui
   compte est ce que l'opérateur peut **lire**.
7. **Un rouge qui ne désigne pas le code.** D-120 : 151 tests sur 215 rouges dans un conteneur
   neuf, sans qu'une ligne ait changé — l'image exportait `NODE_ENV=production`, que Vitest ne
   remplace que s'il est absent. Ce qui rend un run reproductible appartient au dépôt, pas à
   l'environnement.
8. **Un compteur lu d'une source qui ne pouvait pas répondre.** Le dépôt est cloné en
   **`shallow`** ici : `git rev-list --count` n'a jamais compté les commits de la branche, il a
   compté **la profondeur du clone**. « 72 », puis « 85 », puis « 102 » — trois chiffres faux dans
   trois documents, dont deux déjà publiés, pour une seule et même raison. Le vrai compte est
   **225** (`git fetch --unshallow`, confirmé par l'API GitHub). Même famille que D-092 : une
   commande de constat lancée sans vérifier qu'elle *pouvait* répondre, et sa réponse lue comme
   un fait.

---

*Dépôt vert, CI verte. `main` est resté sur `b983097` (bootstrap) : cette branche n'est pas
fusionnée. La **PR #2** la porte, ouverte et à jour. À ne pas confondre avec la **PR #1**, ouverte
sur une **autre** branche (`claude/finance-software-inspiration-88gdl9`, V1), qui ne contient rien
du travail décrit ici.*
