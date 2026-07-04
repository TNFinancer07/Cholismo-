# PRD.md — Terminal Cholismo · Spécification fonctionnelle

Réf. contexte : `CLAUDE.md`. Plan : `TASKS.md`. **Un panneau = un bloc du ContextSchema.**

---

## 0. ContextSchema v1.0 — source de vérité

Modèle Pydantic (backend) + type TS miroir (frontend), synchronisés. **Segmenté par cadence**
(`CLAUDE §6`) : le schéma est un objet, poussé sur des canaux SSE partiels par bloc.

```
ContextSchema
├── session_identity      → ZONE 0     (barre statut)         [statut]
├── s1_state              → B1 gauche  (Sony, cyan)           [rapide]
├── s2_state              → B1 droite  (Youssef, violet)      [lent]
├── bridge_variables      → B2 (+ GEX / âge donnée)           [rapide]
├── sync_state            → B3                                [rapide]
└── unified_signal_output → B4 (score décomposé)              [rapide]

[macro cascade]           → ZONE A   (feed amont, lent)
[overlay cognitif]        → ZONE C   (hors-schéma — discipline)
[decision log]            → ZONE D   (event-sourced, append-only)
```

**Chaque champ porte un `meta`** : `{ value, last_update_ts, source, freshness }` où
`freshness ∈ FRESH | STALE | ABSENT`. Un panneau **doit** rendre un état visuel distinct pour
`STALE` et `ABSENT` (grisé + badge « périmé Xs » / « pas de données »). No signal without data.

```jsonc
{
  "session_identity": {
    "clock_local": "America/Montreal",
    "session_marker": "LONDRES_OBS | OVERLAP_NY | HORS_SESSION",
    "operational_mode": "PRE_SESSION | LIVE | POST_SESSION",
    "operator": "SONY | YOUSSEF",              // instance courante (CLAUDE §9)
    "phase0": "OPEN | BLOCKED",                // moteur déterministe, jamais override UI
    "phase0_blockers": [],                     // liste des règles qui bloquent (→ C1)
    "master_state": "READY | NOT_READY | DEGRADED"
  },
  "s1_state": { "svs_score": 0,
    "order_flow": { "cvd": 0, "absorption": false, "aggressor_ratio": 0 },
    "structure": { "vpoc": 0, "vah": 0, "val": 0, "lvn": [] }, "chop": 0 },
  "s2_state": {
    "cascade": { "nq_es": 0, "vix": 0, "zn": 0, "dx": 0, "eurusd": 0, "real_rates": 0 },
    "bridgewater_matrix": [ /* 5×6 signed intensity */ ],
    "s2_macro_score": { "value": null, "calibrated": false }   // A3 — voir §A3
  },
  "bridge_variables": { "gex": 0, "gex_last_compute_ts": 0,    // → âge, pas countdown
                        "vvix": 0, "dxy": 0 },
  "sync_state": { "verdict": "ALIGNED | DIVERGENT | PARTIAL" },
  "unified_signal_output": {
    "score": 0, "degraded": false,             // degraded=true si macro non calibré
    "breakdown": { "structure": 0, "order_flow": 0, "macro": 0, "sentiment": 0, "quality": 0 },
    "decision": "PENDING | GO | NO_GO"
  }
}
```

**Score unifié** : `Structure*0.35 + OrderFlow*0.25 + Macro*0.20 + Sentiment*0.15 + Quality*0.05`.
Si `s2_macro_score.calibrated == false` → **poids Macro = 0, renormaliser sur 80**, marquer
`degraded=true`. Affiché décomposé (B4).

---

## ZONE 0 — Barre de statut  ·  `session_identity`
Horloge double Montréal+CET, marqueur de session (teinte le fond), sélecteur **3 modes**
(Pré-session · Live · Post-session), **Phase 0 géant OUVERT/BLOQUÉ** (déterministe, reflété
seulement), glyphe état maître (`READY/NOT_READY/DEGRADED`). Badge opérateur courant.

---

## ZONE A — Cascade macro (Youssef, violet) · canal lent

### A1 — Cascade analytique
`NQ/ES → VIX → ZN → DX → EUR/USD`, chaque nœud valeur+delta+couleur régime. **`real_rates`
mis en exergue** (driver primaire, pivot visuel). Nœud périmé → rendu STALE explicite.

### A2 — Matrice Bridgewater
Heatmap 5 dims × 6 axes, intensité signée. Encodage **non seulement par couleur** (motif/
opacité en plus). *Différable — pas MVP (`CLAUDE §10`).*

### A3 — Score macro composite (`s2_macro_score`) — **honnête, pas maquillé**
Tant que non calibré : afficher **`NON CALIBRÉ`**, `value=null`, **contribution live = 0**,
signal marqué `degraded`. La fonction existe mais ne pilote rien avant validation Youssef :

```python
def compute_s2_macro_score(cascade, matrix, real_rates) -> float | None:
    # v1 provisional — calibration owner: Youssef. NE PAS utiliser en live avant validation.
    if not CALIBRATED:            # flag global, défaut False
        return None
    coherence = ...               # accord directionnel cascade vs biais EUR/USD (0–100)
    tilt      = ...               # |intensité signée| moyenne matrice (0–100)
    gate      = ...               # amplificateur taux réels (0.9–1.1)
    return clamp((coherence*0.50 + tilt*0.40 + 10) * gate, 0, 100)
```
A3 montre les intrants (coherence/tilt/gate) même non calibré, pour aider la calibration —
mais jamais un score final trompeur.

---

## ZONE B — Le Router (or) · canal rapide

### B1 — États S1 / S2
Côte à côte, **S1 cyan / S2 violet**, variables clés de chaque. (S2 sur canal lent.)

### B2 — Bridge Variables — **âge de donnée, pas faux countdown**
GEX + **âge réel** = `now − gex_last_compute_ts`, affiché en clair. Au-delà de
`GEX_STALE_SECONDS` (config unique, défaut 180) → badge **STALE**. Pas de compte à rebours vers
une péremption supposée : le TTL dépend de la vitesse réelle du moteur Greeks, inconnue.
Aussi : VVIX, DXY.

### B3 — Sync State
Verdict `ALIGNÉ / DIVERGENT / PARTIEL`. Calculé backend partagé (`CLAUDE §9`).

### B4 — Unified Signal Output — **panneau premier**
Barre segmentée par contribution (35/25/20/15/5). Si `degraded` → bandeau explicite
« MACRO NON CALIBRÉE — signal partiel /80 ». Boutons **Go/No-Go → écrivent un event au
Decision Log**, jamais d'ordre. Déclenche le countdown C3.

```
SIGNAL ████████░░  72/100        [ ⚠ dégradé /80 si macro non calibré ]
 ├─ Structure 35% (28/35) ├─ Order flow 25% (18/25) ├─ Macro 20% (— si NC)
 ├─ Sentiment 15% (8/15)  └─ Qualité 5% (4/5)   → GO / NO-GO [décision humaine]
```

---

## ZONE C — Discipline / état cognitif (pilier 2) · MVP partiel
- **C1** détail Phase 0 : liste `phase0_blockers` actifs.
- **C2** streak → **audit forcé à 8** (proximité du seuil visible).
- **C3** countdown anti-paralysie 90 s, visible en décision pendante uniquement.
  **À expiration → auto `NO_GO` loggé `reason=timeout`. JAMAIS d'entrée forcée.** (Revalider
  que 90 s est cohérent avec l'horizon SVS/S1 ; constante `ANTIPARALYSIS_SECONDS`.)
- **C4** calibration : **deux jauges distinctes** (quanti + comportemental), N/60, sizing 50 %
  verrouillé, Sharpe courant, trades → 50+. Validation séquentielle impossible par design. **(MVP)**
- **C5** self-check cognitif **obligatoire** : bloque le Go tant que non renseigné. **(MVP)**

---

## ZONE D — Decision Log · **event-sourced, append-only**
Event store SQLite, **aucun UPDATE/DELETE**. Trois types d'events immuables :
```
DecisionEvent  : id · ts · operator · schema_snapshot_ref · signal_score · degraded ·
                 decision(GO|NO_GO) · cognitive_selfcheck · reason(nullable: timeout…)
OutcomeEvent   : id · ts · refs DecisionEvent.id · outcome · error_type(A|B|C) · r_multiple
ReconEvent     : id · ts · refs DecisionEvent.id · fill_source · matched(bool)
```
L'« état courant » d'une décision = **projection** rejouant ses events. Barre basse = vue
projetée, horodatée, auditable.

---

## Sous-système — Réconciliation exécution (MVP)
La preuve comportementale exige de lier **décision-terminal ↔ exécution réelle**.
- Import **CSV NinjaTrader** → matché aux `DecisionEvent` par timestamp + instrument →
  `ReconEvent`. Flag `matched=false` si un GO n'a pas de fill correspondant (ou l'inverse).
- Sert au calcul Sharpe et à la preuve des 50+ trades disciplinés.

---

## Sous-système — Console orchestrateur (vue intégrée)
6 sources `SVS · S1 · News · RMS · WS · Youssef` → niveau de risque + action → **payload JSON**.
Statuts VERT/JAUNE/ROUGE (+ forme/icône). Actions `BLOCK_ENTRY · SUSPEND_TRADING · REQUEST_ACK`.
**Logique d'arbitrage = déterministe** : ROUGE + conflit → blocage ; ROUGE sans action →
`REQUEST_ACK` ; aucun trade sans ack humain. Extraire de `/reference/` **uniquement les blocs
`AUTORITÉ`** (`CLAUDE §11`). *Post-MVP.*

---

## Sous-système — Vues par mode (3) · post-MVP
- **Pré-session** (A) : briefing + schéma input/output JSON.
- **Live** (B) : Mode Live — lecture marché, **stack RMS 5 couches**, chat contextuel refusant
  l'entrée si `VIX > 30` ou `CHOP ≥ 61.8`, glossaire inline. Arbres conditionnels du chat :
  traiter comme `PLACEHOLDER` sauf marquage `AUTORITÉ`.
- **Post-session** (C) : rapport JSON strict + sous-processus audit Gemini (20 trades, async).

## Sous-système — Onglet « Prompts & Contextes » · post-MVP
6 blocs copiables (contexte système, Phase A/B/C, audit Gemini, ContextSchema injecté).
Extraire de `/reference/`, ne rien inventer.

---

## Navigation clavier (first-class, MVP)
Focus A/B/C, Go/No-Go clavier en décision pendante, changement de mode, ouverture des vues,
indicateur visuel de focus.

## Rendu transverse
Dark, densité Bloomberg, monospace. **Sony cyan · Youssef violet · Router or**. Risque
**VERT/JAUNE/ROUGE encodé aussi par forme/icône/position** (jamais couleur seule). Un composant
par panneau, un champ du schéma, rendu explicite pour `STALE`/`ABSENT`. Rien hors-schéma.
