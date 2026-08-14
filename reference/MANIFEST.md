# /reference/ — MANIFEST

> Règle (`CLAUDE.md §11`) : seuls les blocs listés `AUTORITÉ` peuvent être extraits comme
> logique métier canonique. Le reste est `PLACEHOLDER` (inspiration UI, jamais canonique).
> En cas de doute → `PLACEHOLDER` + note dans `DECISIONS.md`.

## Artefacts présents

| Fichier | Contenu | Opérateur |
|---|---|---|
| `sony/SVS_System_Prompt_3.html` | **SVS v3.0 — Structural Vacuum Squeeze** (breakout LVN ES/NQ), scoring CHOP intégré | Sony — stratégie d'exécution 1 |
| `sony/strategie2_mean_reversion_v5_afternoon.html` | **Mean Reversion — Piège d'Absorption v5.8** (Bookmap natif, après-midi) | Sony — stratégie d'exécution 2 |
| `youssef/01_FONDATIONS_ET_ANALYSE_QUANTITATIVE.md` | Phase 0 (régime kurtosis VIX) · Étape 0 (quadrant Bridgewater) · N1 · N2A (D1-D5) | Youssef — analyse macro (1/3) |
| `youssef/02_ANALYSE_QUALITATIVE_BLOCS.md` | N2B — blocs 1 à 7 (CB 3 niveaux, narratifs, cross-market, géopolitique, signaux faibles, 10 questions, calibrage) | Youssef — analyse macro (2/3) |
| `youssef/03_SCORING_ARBITRAGES_DECISION.md` | N3 (Flux 1 + Flux 2 / 6 arbitrages) · N4 (validation) · N5 (scénarios + trade card) | Youssef — analyse macro (3/3) |
| `v2/fast-engine/optionsContext.ts` | Lecture du contexte options publié par `options_worker.py` (santé OK/STALE/VENDOR_DOWN/UNAVAILABLE) | Pont Options v2 |
| `v2/fast-engine/gatesO1toO4.ts` | Évaluateurs consultatifs O1 (régime gamma) · O2 (zone d'exclusion) · O3 (obstacle géométrique) · O4 (Net Premium Drift) | Pont Options v2 |
| `v2/fast-engine/o5TailRisk.ts` | O5 — excess kurtosis des log-returns sur barres ES, autonome (aucune dépendance fournisseur) | Pont Options v2 |
| `v2/fast-engine/decisionLog.ts` | Assemblage O1-O5 à l'armement + aplatissement CSV | Pont Options v2 |
| `journal/tradingjournal.html` | **Journal de Session — Sony & Youssef** (app React autonome, localStorage) | Journal de trading commun |

## Classement des blocs

### Pont Options v2 · Fast Engine (`v2/fast-engine/`) — `AUTORITÉ`
Exception explicite à la règle « `/reference/` = maquette » : ces quatre fichiers ne sont pas
une inspiration d'UI, ce sont les **sources autoritaires** du portage Python des balises O1-O5,
et le **verrou de parité** (doctrine D-072) les LIT pour échouer en cas de divergence.

Ils vivent ici et **non** dans `lsr-engine/` parce qu'ils appartiennent au Fast Engine v1.7 —
un autre paquet, avec d'autres dépendances (`redis` côté TS). Les compiler dans le paquet v1.2
cassait son `tsc --noEmit` sans rien apporter : ce dépôt ne les exécute pas, il les porte.

- `AUTORITÉ` — codes de statut, seuils (`O1_SIGNIFICANCE_THRESHOLD`, `O2_EXCLUSION_TICKS`,
  `O3_TOLERANCE_TICKS`, `O4_WINDOW_MS`, `O4_LOCATION_TOLERANCE_TICKS`, `STALE_THRESHOLD_MS`,
  `O5_CONFIG_PLACEHOLDER`), ordre des garde-fous, clé Redis et canal pub/sub.
- **Tous ces seuils restent `PLACEHOLDER` au sens métier** : ils sont autoritaires pour
  l'ÉQUIVALENCE des deux implémentations, jamais pour affirmer qu'ils sont calibrés. Aucun n'a
  été validé sur données.
- Divergences délibérées du port Python : consignées en D-075 (horodatage du futur) et D-076
  (GEX non fini). Toute autre divergence est un bug.


### Sony · SVS (stratégie d'exécution 1) — `AUTORITÉ`
- Identité : breakout par vide de liquidité (LVN) après cassure de Value Area, ES/corrélat NQ.
- Fenêtre prime **09h30–11h00** ; malus session tampon **−3** / zone morte **−7** ; plafond **1 trade zone morte/semaine** (veto dur).
- Seuil unique **score ajusté ≥ 88/100** ; piliers et planchers (compensation interdite) :
  C1 Structure 35 (min 26) · C2 Order Flow 25 (min 19) · C3 Macro&Timing 20 (min 13) ·
  C4 Sentiment 15 (min 10) · C5 Qualité 5 (min 3).
- Filtres absolus Phase 0 : obstacle < 8 ticks · **CHOP(14) 15min ≥ 61.8 bloquant** ·
  divergence de flux/absorption · news Tier 1 ±30 min · corr NQ/ES < +0.40 (purge) ·
  **VIX > 30 = session suspendue**.
- Sizing VIX : <15 → 100 % · 15–20 → 75 % · 20–30 → 50 % · >30 → suspendu ; ×1.00/×0.75/×0.50
  selon tranche de session ; base = 50 % calibration (60 trades).
- Stop-limit uniquement (expiration 90 s), break-even obligatoire à +1.5R, sortie CVD 2 bougies.
- `PLACEHOLDER` : les « corrections d'audit » listées dans le document (non appliquées aux
  seuils en vigueur).
- **Version — tranché par l'opérateur** : la désignation canonique est **SVS v3.0**
  (cohérente avec `CLAUDE.md §3` et le nom du fichier) ; le « v2.0 » de l'en-tête du
  document ne désigne que la version de la matrice de scoring CHOP. Le contenu (seuils,
  filtres, planchers) du fichier fait foi tel quel.

### Sony · Mean Reversion — Piège d'Absorption v5.8 (stratégie d'exécution 2) — `AUTORITÉ`
- Créneau optimal **15h30–17h00** ; hors-fenêtre = floor de pénalité (bordure 0 / intermédiaire
  −5 / lointain −8 ; seuil effectif MAX(seuil, 89)) + cap **1 hors-fenêtre/semaine** + taille ×0.75.
- Seuil **score ≥ 80/100** ; piliers/planchers : Structure 30 (min 21) · Order Flow 25 (min 17) ·
  Macro 25 (min 15) · Sentiment 15 (min 10) · ajustement VWAP +2/+5.
- Gates éliminatoires (fail-fast, ordre v5.1) : verrou 30 min → G1 news High Impact →
  G2 hors VWAP ±1σ → **G4 CI > 61.8** (mean reversion non viable sous ce seuil) → G3 SL défini.
- Buffer SL par CI : >90 → 2 ticks · 75–90 → 5 ticks · 61.8–75 → 3 ticks.
- Modificateur VIX : <15 ×1.0 · 15–20 ×0.75 · 20–30 ×0.50 · **>30 suspendu (CircuitBreaker)** ;
  backwardation VIX9D ≥ VIX → mode ultra-sélectif (seuil 95).
- Taille par score : 80–84 → 25 % · 85–89 → 50 % · 90–94 → 75 % · 95–100 → 100 % ; arrondi 5 % vers le bas.
- Limites : **1 %/trade · 2 %/jour · pause 24 h après 2 pertes** ; erreurs A/B/C.
- **Architecture RMS 5 couches (AUTORITÉ — noms canoniques)** :
  1 `KillSwitch` · 2 `CircuitBreaker` · 3 `StrategyOverlay` · 4 `RiskSizer` · 5 `PortfolioRisk`
  (le garde du dessus prime toujours ; un score de 100 ne franchit jamais une limite au-dessus).

### Youssef · pipeline macro (stratégie d'analyse, 3 fichiers) — `AUTORITÉ`
- **Phase 0 / D4 — régime kurtosis VIX** : GREEN (<15) / YELLOW (15–24) / ORANGE (24–35) /
  RED (>35) ; hystérésis entry/exit 18/14 · 26/22 · 37/33 ; multiplicateurs
  carry 1.0/0.7/0.4/0.0 (⚠ conflit résolu dans le doc : valeurs Arb4 font foi) ·
  fund 1.0/1.0/0.7/0.3 · score 1.0/0.7/0.4/0.0 ; kurtosis > 9 force RED.
- **Étape 0 — quadrant Bridgewater** : classification par signes (g,π), r/θ/confidence,
  transition_risk (<15°/30°), hystérésis zone morte + 3 relevés.
  ⚠ **Conflit de versions constaté entre fichiers** : la table de poids par quadrant du
  fichier 1 (§4, « valeurs canoniques ») diffère de celle du fichier 3 (§N3 Étape 2) pour
  GOLDILOCKS/STAGFLATION/DESINFLATION. **Résolution : fichier 1 fait foi pour WEIGHTS**
  (il se déclare canonique) ; **fichier 3 fait foi pour les 6 arbitrages** (il se déclare
  « version la plus récente, fait foi » sur ce périmètre). Consigné D-021.
- **N3 Flux 1** : renormalisation des poids après modificateur 2B ; `raw = Σ w·D` ;
  `tanh` ; `× d4_mult.fundamental` ; `conviction = |score|×10` (cap 7 si réflexivité Q7) ;
  4 horizons : long `0.5·D1+0.5·D5` · moyen ★ `0.6·D2+0.4·D3` · court `D4_score` · intra flux.
- **N3 Flux 2 — 6 arbitrages** (seuils/caps AUTORITÉ, fichier 3) :
  Arb1 Taylor/OIS |δ|>0.30, cap 9 · Arb2 Phillips/TIPS |δ|>0.25, cap 9 ·
  Arb3 BEER/spot |z|>1.5, cap 6, direction inversée, jamais seul ·
  Arb4 Carry/UIP |signal|>2.0 APRÈS gate carry_mult, cap 8, conviction `min(|s|/2×5, 8)` ·
  Arb5 Cycle |δ|>0.5, timing_factor `1+0.3|leading_turn|`, conviction `min(|δ|/0.5×4×tf, 7)` ·
  Arb6 RR 2 conditions (|z|>1.5 ET divergence>0), cap 6, conviction `min(|z|/1.5×4, 6)`,
  `sentiment_extreme` si |z|>2, boucle de protection carry Arb6→D4→Arb4.
- **N2B** : 7 blocs, verdict B6 par flags (0-2 full · 3-4 half · 5+ no_trade), ordre de
  calibrage A→F, hiérarchie gates > plafonds > confiance > modulations.
- **N4** : 4 tests, table conviction→sizing (≥6 GO plein · 4–6 réduit 30-50 % · 3–4 minimal 20 % · <3 NO-GO).
- **N5** : scénarios 60/30/10 + trade card (R:R ≥ 2:1 visé).
- `PLACEHOLDER` : conviction Arb1/2/3 — le fichier donne les caps mais pas la formule
  d'échelle ; convention retenue `min(|δ|/seuil×5, cap)` (Arb3 : `×4`), calquée sur les
  formules données pour Arb4/5/6. Consigné D-021.

### Journal de trading (`journal/tradingjournal.html`) — `AUTORITÉ`
- 3 vues : **Session · Historique & agrégats · Automatisation** ; stats d'en-tête R total /
  pertes consécutives ; lockout affiché.
- Modèle de fiche (champs canoniques) : direction · prix déclencheur/sortie · CHOP · VIX ·
  corr NQ/ES · taille finale % · **type de sortie (hiérarchie §06)** · palier atteint ·
  **sortie justifiée ? (friction #2)** · **distance SL respectée ?** · résultat R ·
  **erreur A/B/C** · conviction · **Feu N4** (Youssef) · état émotionnel 1-5 · thèse · notes.
- Règles : « SL non respecté ⇒ erreur Type A automatique » ; thèse rédigée avant l'entrée ;
  **« Clôturer & verrouiller » = audit trail immuable** ; sentiment pré/post-session par
  opérateur (humeur/énergie/confiance 1-5 + facteurs) ; agrégats R cumulé/winrate/erreurs/
  **taux friction #2** ; webhooks n8n (`trade_created`, `trade_closed`, `session_closed`,
  `threshold_breached`, `X-API-Key`, grammaire `field_updates`).
- Câblage terminal (D-022) : brouillon = Redis (modifiable/supprimable) → verrouillage =
  entrée **append-only** SQLite (`journal_entries`, mêmes triggers RAISE ABORT) ; lockout
  « 2 pertes → pause 24 h » **dérivé** des entrées, jamais stocké ; CHOP/VIX préremplis
  depuis le schéma live ; webhooks câblés : `trade_closed` + `session_closed` (async,
  loggés) ; `PLACEHOLDER` : `trade_created`/`threshold_breached` non émis, grammaire
  `field_updates` non implémentée (le store du terminal est append-only, pas de patch).

### Câblage terminal (où ces blocs vivent dans le code)
- `backend/app/strategies/sony.py` — éligibilité SVS + Mean Reversion (gates câblés sur les
  données réellement présentes dans le schéma ; gates sans source → `MANUAL`/`ABSENT`,
  jamais inventés) → `s1_state.strategies` → panneau **S1S**.
- `backend/app/strategies/youssef.py` — régime D4 (hystérésis), quadrant + WEIGHTS,
  Flux 1, 6 arbitrages → `s2_state.pipeline` → panneau **S2P**.
- ⚠ Les intrants D1-D5 et deltas d'arbitrage sont produits par le **MockDataSource**
  (simulation des sorties N1/N2A) tant qu'aucun feed réel n'est branché — les FORMULES
  aval sont AUTORITÉ, les VALEURS d'entrée sont simulées (couture mock, CLAUDE §4).
- Stack RMS du Mode Live : noms canoniques des 5 couches (Mean Reversion §01b).
- Onglet Prompts & Contextes : blocs copiables extraits de ces fichiers (plus de gabarits inventés).
