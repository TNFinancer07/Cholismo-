# TERMINAL DE TRADING - CHOLISMO / THE BUILDER
## Fichier 3/3 - Scoring, Arbitrages & Decision (N3 Flux1+Flux2, N4, N5)

> Voir aussi : 01_FONDATIONS_ET_ANALYSE_QUANTITATIVE.md (Phase0/Etape0/N1/N2A D1-D5) et 02_ANALYSE_QUALITATIVE_BLOCS.md (N2B Blocs 1-7).
>
> Note de resolution de conflits : une version anterieure du pipeline (debut-milieu juin) incluait un 7e "arbitrage bonus" (Yield spread 10Y transversal) et une table de coherence a points fixes (+1.5/0/-2.0/-1.0/0). Ces elements ont ete abandonnes au profit de la version la plus recente (fin juin) : 6 arbitrages uniquement, regle de coherence qualitative (confirmation/contradiction/inactif). Les seuils/formules des 6 arbitrages ci-dessous sont la version la plus recente et font foi.

---

## N3 - VUE D'ENSEMBLE : LE JUGE DU PIPELINE

D1-D5 sont les temoins (2A) - le 2B est l'avocat - **N3 est le juge qui rend le verdict**. Le N3 a 2 flux paralleles :
- **Flux 1** : agrege les scores calibres en un verdict directionnel unique (score + conviction + 4 horizons).
- **Flux 2** : scanne 6 arbitrages d'anticipation qui confirment ou contredisent le Flux 1.

**Concept central - l'arbitrage d'anticipation** (pas sans risque) : ton modele predit X, le marche price Y, l'ecart X-Y est l'opportunite. **L'edge retail** : anticiper les mouvements macro avant que le marche les integre dans les OIS ou le spot.

---

## N3 - FLUX 1 : L'AGREGATION (4 etapes separees et auditables)

**Inputs** : 5 scores D1-D5 (de N2A) + calibrage 2B (Bloc 7) + quadrant (Etape 0). **Output** : score final, conviction, 4 horizons. **Position** : N2A -> N2B -> **N3 Flux1** -> N4 -> N5.

**Chaine logique** : 01 Recuperer inputs propres -> 02 Ponderer (poids calibres) -> 03 Agreger (score+conviction) -> 04 Ventiler (4 horizons).

### Etape 1 - Recuperation des inputs (aucun calcul, juste assemblage tracable)
a) Recuperer les 5 scores quantitatifs (N2A). D4 a 2 outputs distincts : `D4_score` (directionnel, utilise dans la somme) et `D4_multiplier` (multiplicatif, applique a la fin).
b) Recuperer le calibrage 2B (Bloc 7) : `w_D2_modifier`, `score_multiplier`, `conviction_cap`, `b6_adjustments`.
c) Recuperer le quadrant Bridgewater (Etape 0) - determine la table de poids par defaut.
d) Valider la coherence des inputs : tous les scores dans [-1,+1] ? quadrant valide ? calibrage complet ? Si invalide -> arret immediat avec log.

**Pourquoi separer cette etape** : separation des responsabilites (audit/debugging). Si tu melanges recuperation et calcul, tu perds la tracabilite.

**Exemple d'inputs (EUR/USD)** :
```python
scores_d = {'D1': -0.76, 'D2': -0.65, 'D3': -0.63, 'D4_score': -0.04, 'D5': -0.28}
calibrage_2b = {'w_D2_modifier': 0.70, 'conviction_cap': None, 'b6_adjustments': 1.5}
quadrant = 'SURCHAUFFE'
```

### Etape 2 - Ponderation selon le quadrant Bridgewater (decision la plus impactante)
a) Selectionner la table de poids selon le quadrant (lookup simple : `weights = WEIGHTS[quadrant]`).
b) Appliquer le modificateur du calibrage 2B (ex : pivot Niv3 detecte -> `w_D2_modifier=0.70` -> poids D2 x0.70, reduction 30%).
c) **Renormaliser pour que la somme = 1.0.** Sans renormalisation, le score final serait artificiellement reduit et les comparaisons inter-paires deviendraient impossibles. Intuition : "D2 moins fiable" signifie que les AUTRES dimensions deviennent relativement plus importantes.

**Code de reference (WEIGHTS complet + apply_weights)** :
```python
WEIGHTS = {
    'SURCHAUFFE':   {'D1':0.15,'D2':0.35,'D3':0.30,'D4':0.10,'D5':0.10},
    'GOLDILOCKS':   {'D1':0.20,'D2':0.20,'D3':0.15,'D4':0.30,'D5':0.15},
    'STAGFLATION':  {'D1':0.15,'D2':0.20,'D3':0.25,'D4':0.25,'D5':0.15},
    'DESINFLATION': {'D1':0.20,'D2':0.30,'D3':0.15,'D4':0.20,'D5':0.15},
}
def apply_weights(quadrant, calibrage_2b):
    w = WEIGHTS[quadrant].copy()
    if calibrage_2b.get('w_D2_modifier'):
        w['D2'] *= calibrage_2b['w_D2_modifier']
    total = sum(w.values())
    w = {k: v/total for k, v in w.items()}   # renormalisation obligatoire
    return w
```
**Exemple** : SURCHAUFFE de base D2=0.35, apres x0.70 -> D2=0.245, somme totale tombe a 0.895 -> renormalise -> poids finaux : **D1=0.168, D2=0.274, D3=0.335, D4=0.112, D5=0.112**.

### Etape 3 - Agregation (le coeur du calcul, 4 sous-etapes)

**3a - la somme ponderee** : `raw_score = w[D1]*d1 + w[D2]*d2 + w[D3]*d3 + w[D4]*d4_score + w[D5]*d5`. Permet la compensation entre dimensions opposees (D1 bearish + D2 bullish s'annulent partiellement).

**3b - la fonction tanh** : `score_pre_gate = tanh(raw_score)`. Borne dans [-1,+1], compresse les extremes (tanh(-3)=-0.995, tanh(0)=0, tanh(+3)=+0.995 - "tres tres fort" n'est pas 3x plus fort que "tres fort").

**3c - le gate D4 (rappel critique : D4 a 2 outputs distincts)**. `D4_score` a deja ete utilise en 3a (contribue a la direction). `D4_multiplier` est applique ICI, separement (affecte l'AMPLITUDE, pas la direction) : `score_final = score_pre_gate * d4_multiplier['fundamental']`. 2 sous-multiplicateurs : `fund_mult` (affecte D1.D2.D3.D5) et `carry_mult` (Arb 4 uniquement).

**3d - conviction + cap reflexivite** : `conviction = abs(score_final) * 10`. Si Bloc6 Q7 a detecte de la reflexivite (narratif Soros) -> `conviction = min(conviction, conviction_cap)` (cap absolu a 7).

**Code complet** :
```python
def compute_final_score(d1, d2, d3, d4_score, d5, w, calibrage_2b, d4_mult):
    raw_score = (w['D1']*d1 + w['D2']*d2 + w['D3']*d3 + w['D4']*d4_score + w['D5']*d5)
    score_pre_gate = np.tanh(raw_score)
    score_final = score_pre_gate * d4_mult['fundamental']
    conviction = abs(score_final) * 10
    if calibrage_2b.get('conviction_cap'):
        conviction = min(conviction, calibrage_2b['conviction_cap'])
    return score_final, conviction
```

**Trace complete EUR/USD (SURCHAUFFE)** :
```
raw_score  = -0.561    (somme ponderee avec poids calibres)
score_pre_gate = tanh(-0.561) = -0.508
d4_mult['fundamental'] = 0.92
score_final = -0.508 * 0.92 = -0.467 (~-0.47)
conviction = abs(-0.467)*10 = 4.7, + 0.9 (ajustement B6) = 5.6
-> DIRECTION FINALE : SHORT EUR/USD, score -0.47, CONVICTION 5.6/10
```

### Etape 4 - Ventilation par horizon temporel (4 frequences simultanees)

**Pourquoi 4 horizons** : un score de -0.41 ne dit pas QUAND la baisse va se produire. Sur 1h EUR/USD peut monter (flux d'execution), sur 1 jour etre range-bound, sur 1 mois baisser de 150 pips. **Un score = une these. Plusieurs horizons = plusieurs executions.**

| Horizon | Periode | Dimensions dominantes | Formule | Role |
|---|---|---|---|---|
| LONG | 4-12 semaines | D1 (cycle) + D5 (structurel) | `score_long = 0.5*D1 + 0.5*D5` | direction de fond |
| MOYEN ★ sweet spot | 1-4 semaines | D2 (CB) + D3 (inflation) | `score_moyen = 0.6*D2 + 0.4*D3` | conviction operationnelle, les arbitrages vivent ici |
| COURT | 1-5 jours | D4 (regime de risque) | `score_court = D4_score` | timing d'entree - si D4 RED, wait peu importe la these |
| INTRA | heures | flux mecaniques (hedge flows, London Fix, EOQ) | overlay d'execution, pas un signal macro | quand passer l'ordre |

**Exemple EUR/USD SHORT** : Long -0.52 (D1+D5) - Moyen ★ -0.64 (D2+D3, le sweet spot) - Court -0.04 (D4, gate quasi neutre) - Intra : flux, London Fix.

### Coherence inter-horizons - regles de trading

| Cas | Condition | Action |
|---|---|---|
| ✓ Cas ideal - alignes | long, moyen, court tous bearish, intra OK | trade plein sizing |
| ⚠ Divergent - attendre | long/moyen bearish, court bullish (D4 risk-on) | attendre que D4 tourne |
| ✗ Conflit - investiguer | long et moyen opposes | transition ou erreur pipeline, pas de trade |

### Output du Flux 1 -> vers Flux 2 et N4
```json
{
  "score_final": -0.47,
  "conviction": 5.6,
  "direction": "SHORT",
  "horizons": {
    "long": -0.52,
    "moyen": -0.64,
    "court": -0.04,
    "intra": "flux"
  }
}
```

**Regle d'or du Flux 1** : chaque etape a une responsabilite separee (assembler, ponderer, agreger, ventiler). Cette separation rend le Flux 1 auditable - quand un trade echoue, tu remontes a l'etape coupable. Sans elle, tu as une boite noire dont tu ne peux pas apprendre.

---

## N3 - FLUX 2 : LES 6 ARBITRAGES D'ANTICIPATION

**Principe transversal a tous les arbitrages** : comparer un modele theorique a ce que le marche price deja. Modele predit X, marche price Y, l'ecart X-Y est l'opportunite. Chaque arbitrage produit : `active` (bool), `delta`, `direction`, `conviction`, `source_dim`, plus des champs distinctifs.

### Tableau de synthese des 6 arbitrages

| Arb | Nom | Formule du delta | Seuil | Horizon | Conviction cap | Source_dim | Question repondue |
|---|---|---|---|---|---|---|---|
| 1 | Taylor/OIS | Taylor gap - spread OIS | 0.30% | 1-4 sem | 9 | D2 | le QUAND (tactique) |
| 2 | Phillips/TIPS | Phillips forecast - TIPS breakeven | 0.25% | 2-4 sem | 9 | D3 | le QUAND (avance, precede Arb1 de 3-6 mois) |
| 3 | BEER/spot | spot - juste valeur BEER | z 1.5 | 6-12+ sem | 6 (le + bas, ex aequo) | D5 | le JUSQU'OU (cible, sans timing) |
| 4 | Carry/UIP | rate_diff - depreciation, gate D4 AVANT seuil | 2.0 apres gate | 1-3 sem | 8 | D2+D4 | le RENDEMENT (gate) |
| 5 | Cycle Divergence | divergence reelle - divergence pricee | z 0.5 | 4-8 sem | 7 (module par timing) | D1 | le POURQUOI (toile de fond) |
| 6 | Risk Reversal | rr_zscore, ET divergence RR vs spot | z 1.5 (2 conditions) | 1-3 sem | 6 (le + bas, ex aequo) | D4 | le SENTIMENT |

**Hierarchie du timing** : Arb3 (aucun timing) < Arb5 (partiel) < Arb1/2 (precis).
**Hierarchie de conviction** : Arb1/2 (9) > Arb4 (8) > Arb5 (7) > Arb3 & Arb6 (6, ex aequo, les plus bas).
**Famille "detection de changement" (candidats ML, Phase 4)** : Arb4 (regime), Arb5 (retournement de cycle), Arb6 (retournement de sentiment, le plus dur pour le ML car le plus bruyant).

---

### ARBITRAGE 1 - Taylor vs OIS (D2)

**Principe** : le Taylor gap dit ce que la CB DEVRAIT faire. L'OIS dit ce que le marche a DEJA price. Le signal est dans l'ECART entre les deux (pas le Taylor gap seul - piege already-priced, voir D2).

**Seuil** : |delta| > 0.30%. **Horizon** : 1-4 semaines (le plus tactique). **Conviction cap** : 9 (le plus haut, avec Arb2 - car timing precis).

**Formule** : `delta = Taylor_gap - ce_que_l_OIS_price_deja`. delta>0 -> marche sous-estime la hawkishite -> quand il se reajuste -> devise monte.

**Output type** :
```json
{"active": true, "delta": 0.35, "direction": "LONG_BASE", "conviction": 9,
 "source_dim": "D2", "horizon": "1-4 sem"}
```

---

### ARBITRAGE 2 - Phillips vs TIPS (D3)

**Principe** : Phillips predit l'inflation future, TIPS breakeven dit ce que le marche anticipe deja. **Precede l'Arbitrage 1 de 3-6 mois** (l'inflation qui monte finit par forcer la CB a agir, ce que l'Arb1 captera plus tard).

**Seuil** : |delta| > 0.25%. **Horizon** : 2-4 semaines. **Conviction cap** : 9.

**Formule** : `delta = Phillips_forecast - TIPS_breakeven` (voir D3 pour le detail complet). delta>0 -> marche sous-estime l'inflation -> CB forcee hawkish -> BULLISH.

**Relation avec Arb1** : si Arb2 dit "hawk" (D3) mais Arb1/D2 dit "dovish" -> transition en cours, reduire la taille, attendre la resolution (D3 anticipe D2).

**Defaults exemple** : EUR phillips 2.5/tips 2.0 -> delta+0.5 ; USD phillips 3.0/tips 2.0 -> delta+1.0 -> arb2_delta base-quote = -0.5 -> SHORT_BASE, conviction 6.0.

**Output type** :
```json
{"active": true, "delta": -0.5, "direction": "SHORT_BASE", "conviction": 9,
 "source_dim": "D3", "precedes": "Arb1", "horizon": "2-4 sem"}
```

---

### ARBITRAGE 3 - BEER vs spot (D5)

**Principe** : arbitrage STRUCTUREL, direction de fond, PAS de timing (le "ressort comprime" peut persister longtemps avant de se detendre). BEER = juste valeur (4 composantes : r_diff, NFA, ToT, productivite/Balassa).

**Seuil** : |z-score misalignment| > 1.5. **Horizon** : 6-12+ semaines (le plus long). **Conviction cap** : 6 (le plus bas, ex aequo avec Arb6).

**Formule** : `misalignment = (spot - BEER) / BEER` ; `z = misalignment / sigma_historique`. **Direction INVERSEE** (retour a la moyenne) : z < -1.5 -> spot sous la juste valeur -> LONG (retour vers le haut).

**Champ distinctif unique** : `requires_confirmation: [D2, D3]` - **"jamais seul"**. L'Arb3 s'auto-declare incomplet : il donne le JUSQU'OU (la cible = le niveau BEER) mais a besoin d'un declencheur tactique (Arb1/2) pour le QUAND.

**Synergie cle** : Arb3 (CIBLE) + Arb1/2 (DECLENCHEUR tactique) = trade complet. Arb3 (CIBLE) + Arb5 (MOTEUR cyclique) = these de fond solide.

**Defaults exemple** : r_diff 0.05, nfa 0.03, tot 0.02, prod 0.02 -> BEER 1.12 ; spot 1.08 ; sigma 2.0 -> misalign -3.57%, z -1.79 -> LONG_BASE, conviction 6.0 (capee).

**Output type** :
```json
{"active": true, "delta": -1.79, "direction": "LONG_BASE", "conviction": 6,
 "source_dim": "D5", "requires_confirmation": ["D2","D3"], "horizon": "6-12+ sem"}
```

---

### ARBITRAGE 4 - Carry / UIP (D2+D4) ★ SEUL a 2 dimensions sources + gate

**Principe** : capture le carry quand l'UIP (parite des taux non couverte) est violee (les devises a haut rendement ne se deprecient pas comme la theorie le predit). D2 = la SOURCE (combien de carry disponible), D4 = le GARDIEN (peut-on le recolter en securite).

**Formules** :
```
uip_violation = uip_implied - realized_depreciation
carry_net = rate_diff - realized_depreciation           (avant le gate)
carry_signal = carry_net * d4_carry_multiplier           (le GATE, applique AVANT le seuil)
```

**Gate D4 (carry_mult)** : GREEN=1.0, YELLOW=0.7, ORANGE=0.4, RED=0.0 (voir fichier 1, section D4/Phase0). **Le gate s'applique AVANT le test du seuil** - un carry de +5% donne un signal actif en GREEN mais totalement neutralise en RED (0%), sans que le carry lui-meme ait change.

**Seuil** : |carry_signal| > 2.0 (APRES le gate). **Horizon** : 1-3 semaines. **Conviction cap** : 8 (tail risk).

**Formule conviction** : `conviction = min(abs(carry_signal)/2.0 * 5, 8)`.

**⚠ Fragilite unique - l'invalidation instantanee** : le carry "monte l'escalier" (gains lents) mais "descend par l'ascenseur" (perte brutale en risk-off). Un passage GREEN->RED annule le carry en HEURES (ex historique : aout 2024, carry JPY). D'ou le champ `regime_dependency` : surveiller le regime en CONTINU, sortir immediatement en cas de passage RED.

**Champs distinctifs** : `source_dim: ["D2","D4"]` (seul arbitrage a 2 dimensions sources) - `d4_gated: true` - `regime_dependency` (surveillance continue, pas ponctuelle).

**Exemple** : rate_diff=6%, depreciation=1% -> carry_net=+5%. En GREEN -> signal +5.0, actif, LONG_BASE, conviction 8.0. En RED -> signal 0.0, inactif (annule par le gate).

**Output type** :
```json
{"active": true, "delta": 5.0, "direction": "LONG_BASE", "conviction": 8,
 "source_dim": ["D2","D4"], "d4_gated": true, "regime": "GREEN",
 "regime_dependency": "surveiller en continu"}
```

**Impact** : le SEUL arbitrage explicitement DEFENSIF - il protege du desastre plutot que d'ameliorer seulement la qualite du signal (le gate empeche de recolter un carry juste avant l'effondrement).

---

### ARBITRAGE 5 - Cycle Divergence (D1) - la toile de fond AVEC timing partiel

**Principe** : detecte quand les cycles economiques de deux pays DIVERGENT (l'un accelere, l'autre ralentit). C'est la TOILE DE FOND directionnelle - entre l'Arb3 (aucun timing) et les Arb1/2 (timing precis), l'Arb5 a un **timing PARTIEL** grace a un input unique : le `leading_turn`.

**Formules** :
```
divergence_reelle = cycle_base - cycle_quote          (indicateurs avances : PMI, OECD CLI, 2s10s, credit impulse)
divergence_pricee = prix_base - prix_quote             (consensus, risk appetite DAX/S&P, taux)
arb5_delta = divergence_reelle - divergence_pricee
timing_factor = 1.0 + 0.3 * abs(leading_turn)          (1.0 a 1.3, amplifie si retournement imminent)
```

**Seuil** : |arb5_delta| > 0.5 (z-score). **Horizon** : 4-8 semaines. **Direction DIRECTE** (pas inversee comme Arb3) : delta>0 -> LONG_BASE (momentum cyclique, on suit la divergence).

**Conviction** : `min(abs(delta)/0.5 * 4 * timing_factor, 7)` - cap 7, module par le timing_factor.

**Champ distinctif unique** : `timing_quality` - eleve = retournement imminent = quasi-tactique (comme Arb1/2) ; faible = divergence stable = toile de fond pure (comme Arb3). **L'Arb5 est le seul dont la NATURE varie** (glisse entre fond et tactique).

**Synergie cle** : Arb5 (MOTEUR, le pourquoi) + Arb3 (CIBLE, le jusqu'ou) + Arb1/2 (TIMING, le quand) = **la these macro complete**, la combinaison la plus solide du pipeline.

**Coherence systeme** : Arb5 (fond) + Arb1/2 (tactique) alignes -> tres haute conviction. Arb5 LONG + Arb1 SHORT -> CB a contre-cycle -> reduire la position, investiguer.

**Exemple** : cycle_base +0.8/cycle_quote -0.4 -> reel +1.2 ; prix_base +0.5/prix_quote -0.1 -> price +0.6 -> arb5_delta=+0.6, leading_turn=0.7 -> timing_factor x1.21 -> LONG_BASE, conviction 5.8, timing_quality eleve.

**Output type** :
```json
{"active": true, "delta": 0.6, "direction": "LONG_BASE", "horizon": "moyen_long_4_8_sem",
 "conviction": 5.8, "source_dim": "D1", "timing_quality": "eleve"}
```

---

### ARBITRAGE 6 - Risk Reversal Divergence (D4) - le capteur de sentiment

**Principe** : lit le Risk Reversal des options FX (`RR = vol_CALL_25delta - vol_PUT_25delta`, le prix de l'assurance directionnelle) pour detecter le sentiment CACHE avant qu'il ne se voie dans le spot. RR positif = calls chers = sentiment haussier ; negatif = puts chers = peur.

**Formules** :
```
rr_zscore = (rr_current - rr_average) / rr_std
divergence = abs(rr_zscore) - abs(spot_momentum)
```
divergence>0 -> le sentiment (RR) est plus extreme que le prix (spot) -> le sentiment PRECEDE le prix -> signal.

**⭐ SEUL arbitrage a exiger DEUX conditions simultanees** :
1. Sentiment extreme : `abs(rr_zscore) > 1.5`.
2. Divergence : `divergence > 0`.
Il faut les DEUX (extreme seul peut deja etre positionne = pas d'edge ; divergence seule peut etre trop faible).

**Direction - confirmation puis CONTRARIAN aux extremes** : z<-1.5 -> SHORT_BASE (peur, confirme la baisse a court terme) ; z>+1.5 -> LONG_BASE (avidite, confirme la hausse). **MAIS** `abs(z) > 2.0` -> flag `sentiment_extreme` = risque de retournement CONTRARIAN (un positionnement trop unanime peut se denouer).

**Conviction** : `min(abs(rr_zscore)/1.5 * 4, 6)` - cap 6 (le plus bas, ex aequo Arb3 - signal bruyant, d'appoint, rarement seul).

**2 champs distinctifs** :
- `sentiment_extreme` (bool) : flag d'auto-avertissement si abs(z)>2.0.
- `regime_context` : le regime D4 actuel - **le meme skew n'a pas le meme sens selon le regime** (RR qui se creuse en GREEN = retournement precoce/signal fort ; le meme RR en RED = juste la confirmation de la panique deja en cours).

**⭐ Fonction speciale unique - la boucle de protection du carry (Arb6 -> D4 -> Arb4)** :
```
Arb6 : RR se creuse sur MXN/ZAR (risk-off naissant)
  -> D4 : le regime se degrade (GREEN -> ORANGE/RED, carry_mult baisse)
    -> Arb4 : le carry est reduit ou annule par le gate
      = PROTECTION : le carry est protege du crash AVANT qu'il n'arrive
```
**C'est le SEUL arbitrage dont l'output AGIT sur un autre arbitrage** (boucle systemique, pas seulement un signal directionnel).

**Usage double** : CONFIRMATION (Arb1 SHORT EUR + Arb6 RR tres negatif -> alignes, forte conviction) OU CAPITULATION contrarian (Arb5 LONG EUR cycle fort + Arb6 RR -2.5 panique extreme -> capitulation -> point bas -> LONG).

**Exemple** : rr_current -1.2, average -0.3, std 0.43 -> z=-2.1 (extreme) ; spot_momentum faible -> divergence>0 -> actif, SHORT_BASE, conviction 5.6, sentiment_extreme=true, regime_context=YELLOW.

**Output type** :
```json
{"active": true, "delta": -2.1, "direction": "SHORT_BASE", "conviction": 5.6,
 "horizon": "court_moyen_1_3_sem", "source_dim": "D4",
 "sentiment_extreme": true, "regime_context": "YELLOW",
 "boucle_carry": "ALERTE -> D4 -> Arb4 reduit/coupe le carry"}
```

---

## LA COHERENCE SCORE + ARBITRAGES -> CONVICTION AJUSTEE

**Regle qualitative retenue (version la plus recente)** :

| Cas | Condition | Effet |
|---|---|---|
| CONFIRMATION | arbitrage dans le meme sens que le Flux1 | +conviction, cas ideal |
| CONTRADICTION | arbitrage oppose au Flux1 | -conviction, investiguer la tension entre dimensions |
| INACTIF | sous le seuil | pas d'ajustement - absence != signal contraire |

### Synergies a rechercher explicitement
- **Arb3 (cible BEER) + Arb5 (moteur cyclique) + Arb1/2 (timing tactique) = la these macro complete.**
- **Arb6 (sentiment) -> D4 -> gate Arb4 = la boucle de protection du carry.**

### Exemple complet trace - EUR/USD, quadrant SURCHAUFFE, tier YELLOW
```
Arb 1 : inactif (delta +0.15 < seuil 0.30)
Arb 2 : ACTIF - SHORT EUR, delta -0.5, conviction 9, moyen 2-4 sem
Arb 3 : inactif (z=-1.2 < 1.5) - biais de fond seulement, pas encore mur
Arb 4 : reduit - carry OK mais tier YELLOW -> carry_mult applique
Arb 5 : inactif - OIS deja pricee (le marche a deja integre le cycle)
Arb 6 : ACTIF - SHORT EUR, rr_z=-1.8 diverge du spot, court 1-5j, conviction 7

-> SHORT EUR/USD, score final -0.41, conviction 5.6/10
-> coherence : 2 arbs actifs alignes SHORT (Arb2, Arb6), 0 contradictoire -> ajustement positif leger
-> calibrage 2B (pivot Niv3 Fed detecte -> D2 x0.70) tempere la conviction (pas de sur-confiance)
-> horizon dominant : moyen 2-4 semaines (Arb2 Phillips/TIPS le plus fort)
-> timing : attendre que D4 repasse GREEN (VIX<19) avant d'entrer a pleine taille
```

**Regle cle sur les horizons** : signal court terme oppose au signal long terme n'est PAS une contradiction - c'est du TIMING. Exemple : BEER dit LONG EUR/USD (12 sem) + surprise CPI hawkish (3 jours, SHORT court terme) -> le LONG de fond reste valide, la surprise CPI filtre juste le MOMENT d'entree. **Erreur classique a eviter** : annuler une these long terme a cause d'un signal court terme oppose.

### Sorties du N3 - vers la suite du pipeline
Validation (N4) - scenarios (N5) - archivage Obsidian (wikilinks : `[[These EUR/USD SHORT]]`, `[[Arb2 actif conv 8]]`, `[[Quadrant Surchauffe]]`).

### Regles d'or du N3
1. Le score final seul est insuffisant - c'est la coherence score + arbitrages qui determine la conviction finale.
2. Arb2 anticipe Arb1 de 3-6 mois - si D3 hawk + D2 neutre, c'est un signal precoce puissant.
3. Arb4 (carry) tuer si VIX>24 (surveillance continue) - Arb6 (RR) s'amplifie en risk-off - Arb3 (BEER) jamais seul (requires_confirmation).
4. Les 4 horizons separent la DIRECTION (long) du TIMING (court) - meme these correcte + mauvais timing = perte.

---

## N4 - VALIDATION (4 tests sequentiels avant le trade)

**Ce que N4 fait - le controle qualite** : la these est construite, N4 est le DERNIER garde-fou avant l'action. Comme un crash test automobile - si elle echoue a un test, retour a l'atelier, on ne livre pas.

**Input** : these N3 (score_final, conviction, arbitrages actifs). **Output** : conviction_finale, sizing, GO/NO-GO, flags de revision.

**Regle fondamentale** : un FAIL est un cadeau. **Un faux PASS est le pire scenario.**

### Sequence des 4 tests (du plus rapide au plus long)

| Test | Nom | Duree | Question posee |
|---|---|---|---|
| T1 | Model Council (Perplexity) | 5 min | "d'autres modeles arrivent-ils a la meme conclusion ?" |
| T2 | Coherence interne pipeline | 2 min | "mes dimensions se contredisent-elles de facon inexplicable ?" |
| T3 | Backtest walk-forward | auto | "ce type de signal a-t-il ete rentable dans le passe ?" |
| T4 | Brain Obsidian historique | 5 min | "mes theses similaires dans le passe ont-elles ete correctes ?" |

### T1 - Model Council (Perplexity) - coherence logique externe, 5 min

**Prompt type** : conditions macro (PMI, OIS spread, CPI surprise, VIX, COT z-score) + "Ma these : SHORT EUR/USD conv 5.6/10, 2-4 semaines, 4 arbs alignes. Question : failles potentielles ? facteurs ignores ? coherence ?"

**Interpretation** :
| Resultat | Condition | Effet |
|---|---|---|
| PASS | 3-4 modeles d'accord | conviction inchangee, signalent les risques mais confirment |
| PARTIAL | 2 vs 2 | angle mort detecte -> conviction -1.0 pt, lire les arguments contre |
| FAIL | 3-4 modeles contre | NE PAS TRADER, retour N2A/2B, erreur probable |

**⚠ Limite critique** : les modeles partagent les memes biais d'entrainement -> peuvent TOUS confirmer une these populaire et fausse. **Le Model Council verifie la coherence logique, PAS la veracite.** Ne JAMAIS augmenter la conviction au-dessus du N3. Il ne lit pas le Niveau 3 des discours CB, ne detecte pas les signaux faibles - TU restes l'analyste principal.

### T2 - Coherence interne du pipeline - 5 checks automatiques, 2 min

| # | Check | Severite | Action si flag |
|---|---|---|---|
| C1 | D1 et D2 meme direction ? sinon transition de quadrant en cours | MEDIUM | conv -0.5, verifier Etape 0 |
| C2 | D3 != D2 sans Arb2 actif ? erreur inputs Phillips ou Taylor | HIGH | conv -1.5, verifier les inputs |
| C3 | D4 RISK_OFF + Arb4 carry actif ? bug dans le gate multiplicateur | CRITICAL | STOP, corriger le code du gate |
| C4 | quadrant Bridgewater coherent avec les signaux dominants ? | MEDIUM | conv -0.5, reviser Etape 0 |
| C5 | score final vs direction des arbs : 2+ contradictoires -> incoherence | HIGH | conv -1.5, ne pas trader |

**Actions par niveau** : CRITICAL -> STOP, bug dans le code, ne JAMAIS trader, corriger et recommencer. HIGH -> conv -1.5, resoudre avant de trader. MEDIUM -> conv -0.5, comprendre la divergence (transition de quadrant ?), noter dans Obsidian, trader si le reste reste coherent, surveiller activement.

### T3 - Backtest walk-forward + PBO + AMH - automatise

**Walk-forward** : train 2 ans, test 6 mois, minimum 30 trades similaires -> hit rate, profit factor, Sharpe. PASS si hit>55%, MARGINAL 45-55%, FAIL <45%.

**PBO (Probability of Backtest Overfitting)** : % de combinaisons OOS perdantes, cross-validation complete. PBO<0.20 -> PASS. 0.20-0.40 -> MARGINAL. >0.40 -> overfit.

**AMH (Adaptive Markets Hypothesis) - degradation** : hit rate rolling 12 mois. Stable -> signal valide. Baisse -> le marche s'adapte au signal, signal mourant. <45% -> suspendre l'arbitrage.

**Seuils realistes macro FX retail** :

| Metrique | Zone realiste | Alerte |
|---|---|---|
| Hit rate | 55-65% | >70% -> trop beau, chercher l'erreur |
| Profit factor | 1.3-2.0 | - |
| Sharpe annuel | 0.8-1.5 | >2.5 -> trop beau |

**⚠ Hit rate>70% ou Sharpe>2.5 = probablement overfit** -> verifier le PBO, chercher un look-ahead semantique residuel, des donnees anachroniques.

**INSUFFICIENT DATA (<30 trades)** : **ce n'est PAS une raison de ne pas trader** -> trader petit (20% de la taille normale) pour construire l'historique.

### T4 - Brain Obsidian historique - apprentissage personnel, 5 min, via Copilot

**4 questions au Copilot Obsidian** :
- Q1 (theses similaires) : "montre-moi les 5 dernieres theses SHORT EUR/USD" -> ex: 3 gagnantes, 2 perdantes -> hit rate 60% -> OK.
- Q2 (hit rate par conviction) : "mes theses conviction 5-6 ont-elles ete fiables ?" -> ex: 54% sur cette tranche -> marginal -> sizing -30%.
- Q3 (pivot Niv3 correct ?) : "quand j'ai detecte un pivot CB Niv3, ai-je eu raison ?" -> ex: 4/6 correct (67%) -> maintenir le calibrage D2 x0.70.
- Q4 (biais frequent) : "quel est mon biais cognitif le plus frequent ?" -> autodiagnostic -> ajuster le processus.

**Boucle d'apprentissage permanente** : these N3 -> trade -> resultat -> Obsidian -> N4 futur. A 20 theses, des patterns commencent a emerger. A 50 theses, le calibrage se raffine par type de signal. A 100 theses, un "facteur de confiance" empirique personnel se degage.

### Exemple complet - EUR/USD, conviction 5.6 entrante

| Test | Resultat | Ajustement | Detail |
|---|---|---|---|
| T1 Model Council | PASS | +0.0 | 4/4 modeles alignes SHORT EUR |
| T2 Coherence | PASS | +0.0 | 0 flags, pipeline coherent |
| T3 Backtest WF | PASS | +0.0 | hit 61%, PF 1.7, Sharpe 1.2 |
| T4 Brain Obsidian | MARGINAL | -0.5 | conv 5-6 : hit rate 54% -> marginal |

**Verdict final** : conviction finale = 5.6 - 0.5 = **5.1**. **GO, sizing REDUIT 30-50%.** Conditions d'entree : attendre D4 tier GREEN (VIX<19), horizon dominant moyen 2-4 sem, invalidant = Fed pivot dovish officiel.

### Table de verdict - conviction finale -> sizing

| Conviction finale | Verdict | Sizing | Note |
|---|---|---|---|
| >= 6.0 | GO | normal, plein sizing | signal fort, tous les tests PASS |
| 4.0 - 6.0 | GO reduit | 30-50% | signal modere, certains flags |
| 3.0 - 4.0 | GO minimal | 20% max | signal faible, construire l'historique |
| < 3.0 | NO-GO | 0 position | reviser la these, retour N2A/2B |

### Les 3 pieges de la validation
1. **Fausse securite du Model Council** : 4 modeles d'accord ne signifie pas monter la taille. Memes biais d'entrainement -> peuvent tous confirmer une these populaire et fausse. **Ne JAMAIS augmenter la conviction au-dessus de N3.**
2. **Backtest parfait = suspect** : hit 75%, Sharpe 2.5, PF 3.0 -> trop beau pour etre reel -> probablement overfit. 55-65% = realiste, >70% = chercher l'erreur.
3. **Pas d'historique != pas trader** : premier signal de ce type -> INSUFFICIENT_DATA n'est PAS une raison d'abandonner -> trader 20%, construire l'historique.

### Sorties de N4
- **GO** -> N5 : scenarios, conviction_finale + sizing determine (scenarios 60/30/10), rapport Agent 4 en Markdown -> Obsidian avec wikilinks `[[These EUR/USD SHORT - date]]`.
- **NO-GO** -> retour N2A/2B : identifier la faille precise, corriger les inputs ou le raisonnement, recalculer le score, repasser N4, noter l'erreur dans Obsidian.

### Regles d'or de N4
1. Un test PASS reduit le risque - un test FAIL est un cadeau - un faux PASS est le pire scenario.
2. Model Council = coherence logique uniquement - ne jamais augmenter la conviction au-dessus de N3.
3. Hit rate 55-65% = realiste - au-dessus de 70% = chercher l'erreur, overfit probable.
4. Brain Obsidian est le SEUL test qui s'ameliore avec le temps - 100 theses = ton propre facteur de confiance.

---

## N5 - SCENARIOS + TRADE CARD (⚠ PARTIEL - specifications eparses, pas d'artefact dedie construit)

> Cette section rassemble tout ce qui existe deja sur le N5 (issu de documents transversaux), mais **le N5 n'a pas encore fait l'objet d'un artefact de reference dedie** comme les autres niveaux. A construire/completer.

**Ce que tu fais** : construire 3 scenarios probabilises, puis en tirer une trade card concrete et un rapport archive dans Obsidian.

**Input** : la these validee par N4 + les niveaux de prix + le regime de risque (pour la taille). **Output** : direction, entree, stop, cible, taille, R:R - tout ce qu'il faut pour passer l'ordre.

### Les 3 scenarios obligatoires

| Scenario | Probabilite | Contenu |
|---|---|---|
| Principal | 60% | la these se realise - catalyseur + cible + invalidant clairs |
| Alternatif | 30% | le marche prend un autre chemin - ce qui le declencherait |
| Tail | 10% | le choc improbable - comment tu te proteges |

### La trade card - structure

| Champ | Contenu |
|---|---|
| Direction | LONG / SHORT |
| Entree | niveau + condition |
| Stop (invalidant) | le niveau qui tue la these |
| Cible | BEER (Arb3) ou structure de marche |
| Taille | f(conviction, regime) |
| Reward:Risk | >= 2:1 vise |

**Regle de sizing** : `risk_pct = f(conviction, regime, flags_bloc6)`. Conviction haute + GREEN + peu de flags -> 1%. Tout ce qui degrade un de ces 3 facteurs reduit la taille. C'est ainsi que le contexte de la Phase 0 et le jugement du Bloc 6 se materialisent en argent reel.

### Exemples de trade cards possibles (memes principes, sizing different)

**Conviction FORTE (conv 7.8, GREEN, 1 flag) -> 1% risk** :
```json
{"dir": "SHORT", "entry": 1.0800, "stop": 1.0880, "target": 1.0620,
 "risk_pct": 1.0, "rr": 2.25}
```
Position pleine. R:R > 2, risque 1% du capital.

**Conviction MOYENNE (conv 5.0, YELLOW, 3 flags) -> 0.5% risk** :
```json
{"dir": "SHORT", "entry": 1.0800, "stop": 1.0860, "target": 1.0680,
 "risk_pct": 0.5, "rr": 2.0}
```
Demi-position. Stop plus serre, risque reduit.

**PAS DE TRADE (5+ flags OU N4 red)** :
```json
{"dir": "STAND_ASIDE", "reason": "B6 veto", "risk_pct": 0.0}
```
La these est notee pour observation, mais non tradee. Aucune honte a passer.

### Exemple complet trace - EUR/USD (a partir du N4 GO ci-dessus)
```
Scenario 60% principal : Fed reste hawkish, inflation US confirme. EUR/USD -> 1.065.
  Catalyseur : CPI US jeudi. Invalidant : > 1.088.
Scenario 30% alternatif : BEER tire l'EUR (Arb3), range. EUR/USD reste 1.075-1.085.
  Declencheur : CPI US mou.
Scenario 10% tail : choc risk-off (RED), denouement carry. EUR/USD spike erratique.
  Protection : stop serre.

Trade card :
{
  "pair": "EUR/USD", "direction": "SHORT",
  "entry": 1.0800, "stop": 1.0880, "target": 1.0650,
  "risk_pct": 1.0, "reward_risk": 1.9,
  "horizon": "moyen 1-4 sem",
  "watch": ["CPI US jeudi", "regime D4", "Arb3 retournement"]
}
```
-> Ordre passe. Rapport Markdown archive dans Brain Obsidian avec wikilinks, pret pour la revue post-trade.

### Sorties de N5
- **GO -> N5** : scenarios (60/30/10), rapport Agent 4 en Markdown -> Obsidian avec wikilinks.
- Apres cloture -> boucle de revue post-trade (voir ci-dessous).

---

## LA BOUCLE DE RETOUR - REVUE POST-TRADE (apres cloture)

**Le resultat nourrit la base historique.** Quand le trade est cloture, ecrire une revue dans Brain Obsidian : la these etait-elle juste ? quel scenario s'est realise ? l'invalidant a-t-il fonctionne ? Cette revue enrichit la base que le N4 du PROCHAIN trade va consulter (T4). **C'est l'Adaptive Markets Hypothesis appliquee : le systeme s'ameliore avec l'experience.**

**Output type** :
```json
{
  "result": "win", "pnl_R": 1.6, "scenario_realise": "60_principal",
  "these_juste": true,
  "lecon": "Arb2 precedes Arb1 a bien anticipe le repricing",
  "tag_obsidian": "#surchauffe #short_eur #arb2_confirme"
}
```

**Regle** : ne jamais sauter cette etape. Un trade non-revu est une lecon perdue - c'est ce qui transforme une serie de paris en une vraie strategie qui apprend.

---

## RECAPITULATIF FINAL - LA TRACABILITE COMPLETE DU PIPELINE

Une seule donnee - le regime GREEN de la Phase 0 - peut voyager jusqu'au bout du pipeline : elle fixe le `d4_carry_multiplier` a 1.0, qui valide l'Arbitrage 4 (carry MXN), influence le gate du Flux 1, et determine la taille de position en N5.

**Rien n'est isole. Chaque output est un input tracable.** Quand un trade echoue, on remonte la chaine - Phase 0 -> Etape 0 -> N1 -> N2A -> N2B -> N3 -> N4 -> N5 - et on trouve exactement l'etape coupable. Quand un trade reussit, la boucle de revue grave la lecon dans la base.

**C'est cette tracabilite de bout en bout qui transforme une intuition en processus, et un processus en strategie qui apprend.**
