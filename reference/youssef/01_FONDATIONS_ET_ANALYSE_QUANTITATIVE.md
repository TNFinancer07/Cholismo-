# TERMINAL DE TRADING — CHOLISMO / THE BUILDER
## Fichier 1/3 — Fondations & Analyse Quantitative (Phase 0 → Étape 0 → N1 → N2A / D1-D5)

> Ce document consolide, sans perte d'information factuelle/logique, l'ensemble des spécifications produites pour le pipeline d'analyse macro FX de Youssef. Il est destiné à servir de brief technique pour la construction du terminal (Claude Code). Voir aussi : `02_ANALYSE_QUALITATIVE_BLOCS.md` et `03_SCORING_ARBITRAGES_DECISION.md`.
>
> **Règle de résolution des conflits de versions** : quand deux sources se contredisaient, la version la plus récente (par date de production) a été retenue. Les cas de conflit résolus sont signalés explicitement (⚠ RÉSOLU).

---

## 0. CONTEXTE DU PROJET (mémoire long-terme, pas issu d'un artefact)

**Projet** : Cholismo / The Builder — écosystème de trading assisté par IA pour futures ES/NQ et FX EUR/USD, ciblant une démo live à l'automne 2026.

**Architecture double-opérateur** :
- **Profil Youssef** — macro FX (ce document) : matrice Bridgewater, 5 dimensions, 6 arbitrages, cascade macro NQ/ES → VIX → ZN → DX → EUR/USD.
- **Profil Sony** — microstructure intraday ES/NQ : order flow, stratégie de breakout SVS v3.0, Stratégie S1/2 mean reversion (hors périmètre de ce document).

**Philosophie centrale** : human-in-the-loop. L'IA score, filtre et orchestre ; l'humain garde l'autorité finale Go/No-Go. Aucune exécution d'ordre automatisée. La discipline est encodée dans l'infrastructure, pas dans la seule volonté.

**Phase de construction actuelle** : démo, avec condition de passage au live nécessitant simultanément 50+ trades avec Sharpe positif ET une preuve comportementale.

**Composants d'infrastructure globale (au-delà du périmètre macro FX)** :
- `ContextSchema v1.0` — 6 blocs : Session Identity, S1 State, S2 State, Bridge Variables, Sync State, Unified Signal Output.
- Formule de scoring des signaux : Structure 35% / Order Flow 25% / Macro 20% / Sentiment 15% / Quality 5%.
- **Phase 0 (discipline)** : gate de discipline absolu — bloqueurs pré-trade inviolables, ne peut être outrepassé par aucun système externe, réponse n8n ou output IA.
- Risk controls transverses : streak tracking (audit trigger à 8 pertes consécutives), anti-paralysis countdown 90s, calibration 60 trades avec position sizing verrouillé à 50%, Decision Log append-only.
- Orchestration : Cholismo (6 sources de signaux : SVS, S1, News, RMS, WS, Youssef), logique fail-closed, arbitrage de conflits, statuts VERT/JAUNE/ROUGE, payload JSON structuré.
- Stack technique cible : FastAPI, Redis, SQLite, SSE, React ; Groq+LLaMA 3.3 70B (checks binaires <100ms), Gemini 2.5 Pro (audits périodiques 20-trades), n8n + LangGraph (orchestration), Claude (arbitrage/scoring final).

**BLOCKERS TECHNIQUES OUVERTS (non résolus, à traiter avant l'implémentation complète)** :
1. `s2_macro_score` — méthode de calcul composite non arrêtée (bloque le Panel A3 du layout terminal).
2. Vitesse du moteur de Greeks de Sony — affecte la précision du GEX TTL (Panel B2).

---

## 1. GLOSSAIRE DE RÉFÉRENCE

| Terme | Définition |
|---|---|
| base / quote | Dans EUR/USD, EUR = base (1ere devise), USD = quote (2e). Acheter la paire = parier que la base monte face à la quote. |
| hawkish / dovish | Hawkish = banque centrale veut monter les taux (bon pour la devise). Dovish = veut baisser (mauvais). |
| Taylor gap | Ecart entre le taux qu'une CB devrait appliquer (regle de Taylor) et celui qu'elle applique reellement. |
| OIS | Overnight Index Swap - indicateur des taux futurs deja anticipes par le marche. "Ce qui est deja price." |
| already-priced | Quand une info est connue de tous, le marche l'a integree - elle ne bouge plus le prix. |
| dot plot | Graphique ou chaque membre FOMC projette ou iront les taux - sondage interne. |
| NLP tone | Ton (optimiste/inquiet/ferme) extrait des discours de banque centrale par IA. |
| output gap | Ecart entre production reelle et production potentielle. Positif = surchauffe, negatif = mou. |
| z-score | Mesure du caractere inhabituel d'une valeur. 0 = normal, +2/-2 = tres au-dessus/dessous de la normale. |
| tanh | Fonction mathematique bornant une valeur dans [-1,+1], compressant les extremes (limiteur de volume). |
| carry trade | Emprunter dans une devise a faible taux pour placer dans une devise a taux eleve, empocher le differentiel. |
| UIP | Uncovered Interest Parity - theorie voulant qu'une devise a taux eleve se deprecie pour compenser. Souvent violee en pratique. |
| BEER | Behavioral Equilibrium Exchange Rate - modele de juste valeur long terme d'une devise. |
| Risk Reversal | Thermometre de peur/avidite du marche des options - ecart de volatilite implicite calls vs puts. |
| PairBundle | EconomyBundle(base) - EconomyBundle(quote) - principe d'assemblage de toute paire. |

---

## 2. VUE D'ENSEMBLE DU PIPELINE

```
PHASE 0 (quotidien) -> regime kurtosis VIX -> contexte de risque du jour
   v
ETAPE 0 (mensuel, revise si choc) -> quadrant Bridgewater -> poids D1-D5
   v
N1 (hebdomadaire) -> collecte modulaire par economie -> assemblage par paire
   v
N2A (hebdomadaire) -> scoring quantitatif D1-D5 -> 5 z-scores [-1,+1]
   v
N2B (hebdomadaire) -> calibrage qualitatif 7 blocs -> 1 fiche calibree
   v
N3 FLUX 1 -> agregation ponderee (tanh + gate D4) -> score, conviction, 4 horizons
N3 FLUX 2 -> 6 arbitrages d'anticipation -> confirment/contredisent le Flux 1
   v
N4 (par trade) -> validation (Model Council, coherence, backtest, Obsidian) -> GO/NO-GO
   v
N5 (par trade) -> scenarios 60/30/10 + trade card -> decision executable
   v
BOUCLE (apres cloture) -> revue post-trade -> Brain Obsidian -> ameliore le N4 futur
```

**Regle absolue** : chaque niveau produit un output qui devient l'input du suivant ; rien ne se court-circuite. Un score sans calibrage est aveugle, un trade sans validation est un pari, un trade sans revue est une lecon perdue.

### Les 3 cadences

| Cadence | Composants |
|---|---|
| QUOTIDIEN | Phase 0 (dashboard) - D4 (regime de risque, temps reel continu) - Arb 6 (sentiment/Risk Reversal) - surveillance positions - alerte invalidants |
| HEBDOMADAIRE | N1 (rafraichissement bundles) - N2A (scoring D1-D5) - N2B (7 blocs) - N3 Flux1+Flux2 complet - scan signaux faibles (Bloc 5) |
| MENSUEL | Etape 0 (quadrant) - D5 (BEER recalcule) - N4 (backtest global) - revue Obsidian globale - ajustement des seuils |

**Exceptions qui forcent un re-run immediat** : choc geopolitique (Bloc 4, permanence 4-5) OU 2+ cassures de correlation simultanees (Bloc 3).

### Session type - exemple chronologique (EUR/USD, lundi matin)

| Heure | Duree | Etape | Resultat |
|---|---|---|---|
| 08:00 | 15 min | Phase 0 | VIX 14, stable -> regime GREEN. Carry valide. |
| 08:15 | 5 min | Etape 0 | Quadrant confirme : SURCHAUFFE. Poids favorisent D2/D3. |
| 08:20 | 20 min | N1 + N2A | D1 -0.76, D2 -0.65, D3 -0.63, D4 -0.04, D5 -0.28. Tout bearish EUR. |
| 08:40 | 30 min | N2B | Bloc 1 : BCE retire "data-dependent" -> shift dovish. Bloc 6 : 1 flag -> trade plein possible. |
| 09:10 | 15 min | N3 Flux 1 | raw -0.561 -> tanh -0.508 -> gate x0.92 -> score -0.47. Conviction 5.6. SHORT EUR/USD. |
| 09:25 | 20 min | N3 Flux 2 | Arb1 inactif. Arb2 SHORT actif. Arb4 LONG MXN (carry GREEN). Arb6 confirme la peur EUR. |
| 09:45 | 15 min | N4 | Perplexity ne contredit pas. Backtest hit rate 64%. Obsidian : setup similaire gagnant en mars. Feu vert. |
| 10:00 | 15 min | N5 | Scenario 60% : EUR/USD -> 1.065. Entree 1.080, stop 1.088, cible 1.065, R:R 1.9:1, taille 1%. Ordre passe. |

~2h pour une analyse complete. Phase 0, D4 et Arb 6 tournent ensuite en surveillance continue pendant que la position est ouverte.

### Tracabilite de bout en bout
Une seule donnee - le regime GREEN de la Phase 0 - voyage jusqu'au bout : elle fixe le d4_carry_multiplier a 1.0, qui valide l'Arbitrage 4 (carry), influence le gate du Flux 1, et determine la taille de position en N5. Rien n'est isole. Chaque output est un input tracable.

---

## 3. PHASE 0 - REGIME DE RISQUE MATINAL (kurtosis VIX)

**Frequence** : quotidien, ~15 min. **Role** : fixer le contexte de risque du jour AVANT toute analyse de paire.

### Ce que tu fais
Lecture croisee du morning dashboard : ES/NQ (appetit pour le risque), VIX (peur), ZN 10Y (taux longs), DX (force du dollar), 6E (euro). Chercher la coherence ou les divergences entre ces marches. Puis classer le regime kurtosis via le VIX, et verifier le calendrier des hedge flows (fin de mois/trimestre, London Fix 16h).

### Les 4 regimes possibles

| Regime | Condition | vix ex. | carry_mult | fund_mult | Implication |
|---|---|---|---|---|---|
| GREEN | VIX < 15, stable | 14.2 | 1.0 | 0.92 | Carry pleinement valide. Positions de portage (MXN, ZAR) permises. |
| YELLOW | VIX 15-24 | 17.5 | 0.7 | 0.85-1.0 | Carry reduit ~30%. Alleger les positions de portage existantes. |
| ORANGE | VIX 24-35 | 24.0 | 0.4 | 0.7 | Carry fortement reduit. Pas de nouveau carry, proteger l'existant. |
| RED | VIX > 35, spike | 35.0 | 0.0 | 0.3-0.5 | Carry ANNULE. Sortie immediate des positions de portage. Dollar refuge. |

**RESOLU - conflit sur les multiplicateurs de carry** : un document D4 anterieur donnait YELLOW=0.6/ORANGE=0.3 ; la spec Arbitrage 4 (plus recente) donne YELLOW=0.7/ORANGE=0.4. **La valeur retenue pour carry_mult est celle de l'Arbitrage 4 : GREEN=1.0 / YELLOW=0.7 / ORANGE=0.4 / RED=0.0.** Les valeurs fund_mult/score_mult (issues du D4) ne sont pas concernees par ce conflit.

### Regle de lecture temps reel
Le seul chiffre a regarder en premier le matin est le VIX. Il determine si la journee autorise le carry (GREEN) ou l'interdit (RED). Un passage GREEN -> RED en cours de position carry = signal de sortie immediat, pas de reflexion.

### Output -> alimente D4 + gate carry
```json
{
  "regime_kurtosis": "GREEN",
  "vix": 14.2,
  "es_nq_trend": "risk_on",
  "zn_10y": 4.25,
  "dx": 104.5,
  "6e": 1.0805,
  "hedge_flows": "none",
  "d4_carry_multiplier": 1.0,
  "d4_fund_multiplier": 0.92
}
```

---

## 4. ETAPE 0 - MATRICE BRIDGEWATER (le quadrant macro)

**Frequence** : mensuel, revise si choc. **Role** : LA decision la plus importante du pipeline - determine quelles dimensions D1-D5 comptent le plus.

### Le principe
La matrice n'est pas une carte ("achete EUR/USD"), c'est une boussole : elle dit dans quel environnement economique on navigue, a partir de deux forces - g (momentum de croissance) et pi (momentum d'inflation). Ce qui compte n'est pas le NIVEAU mais la DIRECTION relative a ce qui est deja price.

### Les 2 axes
- **Axe g (croissance)** : PMI momentum, OECD CLI, Citi Surprise Index, credit impulse, output gap.
- **Axe pi (inflation)** : core PCE/CPI momentum, breakeven TIPS, inflation surprise, wage growth, input prices.

### Les 4 quadrants

| Quadrant | Condition | CB / marche | Dimensions dominantes |
|---|---|---|---|
| SURCHAUFFE | g up pi up | CB doit durcir | D2 (0.35) + D3 (0.30) |
| GOLDILOCKS | g up pi down | Risk-on, carry roi | D4 (0.30) |
| STAGFLATION | g down pi up | CB piegee, dangereux | D3 (0.25) + D4 (0.25) |
| DESINFLATION | g down pi down | CB peut assouplir | D1 (0.30) + D2 (0.30) |

Un D4 carry +0.8 pese 0.10 en SURCHAUFFE (negligeable) mais 0.30 en GOLDILOCKS (dominant). Une erreur de quadrant se propage a tout le pipeline.

### Table des poids par quadrant (valeurs canoniques, somme=1.0)
```json
{
  "SURCHAUFFE":  {"D1":0.15,"D2":0.35,"D3":0.30,"D4":0.10,"D5":0.10},
  "GOLDILOCKS":  {"D1":0.20,"D2":0.15,"D3":0.10,"D4":0.30,"D5":0.25},
  "STAGFLATION": {"D1":0.15,"D2":0.15,"D3":0.25,"D4":0.25,"D5":0.20},
  "DESINFLATION":{"D1":0.30,"D2":0.30,"D3":0.10,"D4":0.15,"D5":0.15}
}
```

### La construction mathematique - z-score -> polaire -> quadrant
1. Normalisation : `z = (x - mu_fenetre) / sigma_fenetre` sur fenetre glissante 60 mois, ddof=1, borne [-3,+3].
2. Agregation : `g = somme(poids_i * z_croissance_i)` ; `pi = somme(poids_j * z_inflation_j)`.
3. Polaire : `r = sqrt(g^2 + pi^2)` (force/nettete) ; `theta = atan2(pi, g)` (position, 45/135/225/315 = centre pur, 0/90/180/270 = frontiere) ; `confidence = min(r/0.8, 1.0)` ; `d_boundary = min(theta%90, 90-(theta%90))` -> transition_risk high si <15 deg, moderate 15-30, low >30.

Exemple : g=+0.62, pi=+0.48 -> r=0.78, theta=37.7 deg, confidence=0.80, transition faible -> SURCHAUFFE net.

### Derive progressive (jamais de saut brutal)
1. **Z-score glissant** (60 mois) : le referentiel evolue lentement.
2. **EMA** : `g_lisse = alpha*g_brut + (1-alpha)*g_lisse(hier)`, alpha=0.15 recommande (alpha=0.05 ultra-stable ~20 mois, alpha=0.30 reactif ~3 mois plus bruyant).
3. **Hysteresis anti flip-flop** : zone morte (|coord|<0.10) + confirmation sur N=3 releves consecutifs.

Exemple d'evolution 12 mois (SURCHAUFFE -> GOLDILOCKS) : la bascule a pris ~11 mois, visible des avril (transition_risk high), confirmee 3/3 en octobre.

### Code de reference
```python
def classify(self, g, pi):
    r = np.sqrt(g**2 + pi**2)
    theta = np.degrees(np.arctan2(pi, g)) % 360
    if g >= 0 and pi >= 0: cand = 'SURCHAUFFE'
    elif g < 0 and pi >= 0: cand = 'STAGFLATION'
    elif g < 0 and pi < 0: cand = 'DESINFLATION'
    else: cand = 'GOLDILOCKS'
    # HYSTERESIS : zone morte + confirmation sur N relevés consécutifs
    current = self.state['quadrant']
    in_dead_zone = abs(g) < self.dead_zone or abs(pi) < self.dead_zone
    confidence = min(r / 0.8, 1.0)
    d_boundary = min(theta % 90, 90 - (theta % 90))
    transition = 'high' if d_boundary < 15 else 'moderate' if d_boundary < 30 else 'low'
    return quadrant, r, theta, confidence, transition
```

### Automatisation - boucle quotidienne
1. fetch (Perplexity : donnees + consensus + ton CB) -> 2. compute (code pur) -> 3. persist (JSON) -> 4. alert (bascule/transition).
```python
from apscheduler.schedulers.blocking import BlockingScheduler
sched = BlockingScheduler()
engine = BridgewaterEngine(alpha=0.15)
@sched.scheduled_job('cron', hour=7)
def daily():
    engine.run()
```

### Repartition IA

| Etape | IA ? | Qui / comment |
|---|---|---|
| Collecte sous-indicateurs | OUI (fort) | Perplexity |
| Z-score / agregation / EMA / classification / polaire / mapping poids | NON | code pur (numpy) |
| Validation du quadrant | oui | Perplexity (Model Council) |
| Interpretation transition | OUI (fort) | Claude + Perplexity |
| Conception de W | OUI (fort) | Claude (one-time) |
| Narration de la bascule | oui | Claude |

Principe : l'IA entoure le coeur, elle ne le penetre jamais. Perplexity = les yeux, Claude = le cerveau, numpy = la regle. Premier "Agent Macro" du roadmap (8 agents orchestres par un Brain AI).

### Output complet
```json
{
  "quadrant": "SURCHAUFFE", "g": 0.62, "pi": 0.48, "r": 0.78, "theta": 37.7,
  "confidence": 0.80, "transition_risk": "low",
  "weights": {"D1":0.15,"D2":0.35,"D3":0.30,"D4":0.10,"D5":0.10},
  "dominant_dims": ["D2","D3"], "regime_changed": false, "last_review": "2026-06-01"
}
```
Pilote 3 choses : weights (pondération Flux 1), confidence (facteur conviction), transition_risk (surveillance).

**Regle de re-classification automatique** : 2+ cassures de correlation (Bloc 3) OU choc permanence 4-5 (Bloc 4) -> recalcul immediat.

---

## 5. N1 - COLLECTE MODULAIRE

**Frequence** : hebdomadaire (continu pour certaines sources). **Role** : construire les donnees brutes, economie par economie, jamais paire par paire.

### Le changement de paradigme
AVANT : collecte figee par paire (non extensible). APRES : 1 template universel x 1 instance par devise -> n'importe quelle paire s'assemble a la demande, scan multi-paires automatique. Tu collectes des ECONOMIES, tu trades des PAIRES.

### Le template universel - 6 blocs identiques par economie

| Bloc | Contenu |
|---|---|
| 01 Taux et courbe | rate_2y, rate_10y, rate_3m, spread_10y2y, ois_1y, policy_rate |
| 02 Inflation | cpi_headline, cpi_core, pce_equiv, breakeven_5y, cpi_surprise_z |
| 03 Croissance | pmi_composite, gdp_qoq, ip_mom, retail_sales, gdpnow_equiv |
| 04 Emploi | unemployment_u3, jobs_created, wages_ahg, participation_rate |
| 05 Banque centrale | policy_rate, guidance, tone_score_nlp, next_meeting_date |
| 06 Position/flux | cot_net (si dispo), current_account, trade_balance |

```python
EconomyDataBundle(currency='USD', rates={...}, inflation={...}, growth={...},
                   employment={...}, cb={...}, flows={...},
                   triple_timestamp=True, validated=True, ingestion=datetime)
```

### Univers couvert
**G10** : USD (Fed, reference) - EUR (BCE) - JPY (BoJ, safe haven ultra-dovish) - GBP (BoE) - CHF (SNB, safe haven, interventions) - CAD (BoC, lie petrole WTI) - AUD (RBA, risk-on proxy) - NZD (RBNZ, carry proxy).
**Emergentes** : MXN (Banxico, carry trade favori) - ZAR (SARB, tres volatile).

**Precautions emergentes** : controle de capitaux -> UIP/Mundell-Fleming fragile ; risque politique fort -> D5 domine sur D2/D3 ; liquidite reduite -> spread eleve.

### Triple timestamp - integrite temporelle (anti look-ahead bias)

| Timestamp | Definition | Exemple |
|---|---|---|
| as_of_date | La periode que la donnee mesure | CPI janvier 2024 |
| release_datetime (critique) | Quand publie officiellement | 13 fev 2024, 08h30 ET |
| ingestion_datetime | Quand l'agent l'a lu | 13 fev 2024, 08h31:05 |

**Piege qui detruit les backtests** : utiliser une donnee a une date ou elle n'etait pas encore publiee = voyage dans le futur. Sharpe 3.5 backtest -> -40% live, meme systeme.

```python
def get_available(series, trading_date):
    return df[df['release_datetime'] <= trading_date]['value'].iloc[-1]
```

Chaque economie publie selon son fuseau (NFP US vendredi 08h30 ET, CPI UK mercredi 07h00 GMT, CPI Japon vendredi 23h30 GMT). Ne jamais melanger les release_datetime entre economies.

### Calendrier de latences reelles (exemples)

| Donnee | Economie | Periode | Publication | Delai |
|---|---|---|---|---|
| NFP emplois | USD | janvier 2024 | 2 fev 2024 | +32j |
| CPI All Items | USD | janvier 2024 | 13 fev 2024 | +44j |
| GDP Q4 1ere estim. | USD | Q4 2023 | 25 jan 2024 | +25j |
| GDP Q4 revise | USD | Q4 2023 | 28 fev 2024 | +59j |
| HICP flash | EUR | janvier 2024 | 31 jan 2024 | +31j |
| CPI | GBP | janvier 2024 | 14 fev 2024 | +45j |
| COT EUR/USD | CFTC | sem 30/01 | 2 fev 2024 | +3j |
| Taux DGS/TIPS | FRED | quotidien | J+1 | +1j |

Au 5 janvier 2024, AUCUNE donnee mensuelle de janvier n'est disponible pour AUCUNE economie.

### Assemblage de paires a la demande
```
PairBundle = EconomyBundle(base) - EconomyBundle(quote)
EUR/USD = EUR_bundle - USD_bundle
GBP/JPY = GBP_bundle - JPY_bundle
```

### Scan multi-paires du matin
Calcule la divergence sur toutes les paires assemblables (G10+MXN+ZAR), classe par |score| de divergence.
```
PAIRE     SCORE  DIVERGENCE MACRO                                CONVICTION
EUR/USD   -0.72  Fed hawkish +0.80% - BCE dovish - Taylor gap fort   8/10
GBP/JPY   +0.61  BoE hawkish - BoJ ultra-dovish - yield spread fort  7/10
AUD/USD   +0.34  risk-on actif - carry RBA - COT neutre              5/10
USD/MXN   -0.28  taux reels MXN eleves - carry Banxico               4/10
-> trader EUR/USD et GBP/JPY - ignorer les 2 dernieres (conviction insuffisante)
```

### Validation avant N2A
1. Completude (6 blocs presents) 2. Timestamps (release <= ingestion) 3. Outliers (z-score flag) 4. Fraicheur (staleness check)
```python
MacroDataBundle(economies=['USD','EUR','GBP','JPY'], pairs=['EURUSD','GBPJPY'], validated=True)
```

### Regles fondamentales
1. Garbage In, Garbage Out.
2. Tu collectes des ECONOMIES, tu trades des PAIRES - jamais l'inverse.
3. Le triple timestamp est non negociable.
4. Perplexity Sonar = contexte narratif uniquement - jamais source pour backtest quantitatif.

---

## 6. N2A - SCORING QUANTITATIF DES 5 DIMENSIONS (D1-D5)

Chaque dimension transforme les donnees brutes du N1 en un z-score normalise [-1,+1]. D4 est special (double output). Correspondance : D1<->Arb5, D2<->Arb1, D3<->Arb2, D4<->Arb4/6, D5<->Arb3.

### D1 - Le Cycle Economique

**Essence** : mesure la divergence de VITESSE entre deux economies dans leur cycle - jamais le niveau absolu.

**5 indicateurs (poids)** : PMI composite 0.30 - Output gap Hamilton 0.25 - LEI 0.20 - Sahm rule 0.15 - IP/retail 0.10.

**Cascade** :
1. Z-score : `z=(x-mu)/sigma`, fenetre 252j, ddof=1, clip[-3,+3].
2. Divergence : `diff_i = z_base_i - z_quote_i`.
3. Timing factor : `sign(pmi)==sign(ip) -> 1.0` sinon `-> 0.7` (incoherence = retournement probable, -30%).
4. Agregation : `raw = somme(poids_i*diff_i)` ; `d1 = tanh(raw) * timing_factor * confidence`.

**Exemple EUR/USD** (base=EUR, quote=USD) :

| Indicateur | z EUR | z USD | diff | poids | contribution |
|---|---|---|---|---|---|
| PMI | -0.55 | +0.90 | -1.45 | 0.30 | -0.435 |
| output gap | -0.45 | +0.65 | -1.10 | 0.25 | -0.275 |
| LEI | -0.55 | +0.55 | -1.10 | 0.20 | -0.220 |
| Sahm | +0.20 | -0.10 | +0.30 | 0.15 | +0.045 |
| IP retail | -0.50 | +0.60 | -1.10 | 0.10 | -0.110 |

raw=-0.995, timing=1.0 -> **d1 = tanh(-0.995) = -0.76**

```python
class D1CycleScorer:
    def __init__(self, window=252):
        self.window = window
        self.weights = {'pmi':0.30,'output_gap':0.25,'lei':0.20,'sahm':0.15,'ip':0.10}
    def zscore(self, value, history):
        w = history[-self.window:]
        mu, sigma = np.mean(w), np.std(w, ddof=1)
        return np.clip((value-mu)/sigma, -3, 3) if sigma > 0 else 0.0
    def compute(self, base, quote):
        zb = {k: self.zscore(base[k], base.hist[k]) for k in self.weights}
        zq = {k: self.zscore(quote[k], quote.hist[k]) for k in self.weights}
        diff = {k: zb[k]-zq[k] for k in self.weights}
        timing = 1.0 if np.sign(diff['pmi'])==np.sign(diff['ip']) else 0.7
        raw = sum(self.weights[k]*diff[k] for k in self.weights)
        d1 = np.tanh(raw) * timing
        return {'d1_score': round(d1,3), 'timing_factor': timing, 'components': diff}
```

**Automatisation** : declenche par le N1 (invalidation ciblee sur paires "dirty"), pas une boucle en continu. Cadence lente (hebdo/mensuel), 100% numpy.

**Cas limites** : timing_factor=0.7 (retournement probable) - Sahm qui s'active (retournement majeur) - divergence faible d1~0 (pas d'edge) - indicateur manquant (confidence attenuee).

**IA** : conception one-time (Claude) + verification legere amont + interpretation optionnelle aval. Zero IA dans le calcul - le plus deterministe, usage global FAIBLE.

**Output** :
```json
{"d1_score": -0.76, "direction": "bearish", "timing_factor": 1.0, "confidence": 0.95,
 "components": {"pmi_diff":-1.45,"og_diff":-1.10,"lei_diff":-1.10,"sahm_diff":0.30,"ip_diff":-1.10}}
```
-> N2A - Arb 5 (Cycle Divergence) - Brain Obsidian.

**Poids par quadrant** : SURCHAUFFE 0.15 - GOLDILOCKS 0.20 - STAGFLATION 0.15 - DESINFLATION 0.30 (DOMINANT).

---

### D2 - La Politique Monetaire

**Essence** : dimension la plus importante du pipeline (poids max 0.35). Combine TROIS angles : modele theorique (Taylor), marche deja price (OIS), communication CB (NLP tone + dot plot).

**4 composantes (poids)** : Taylor gap 0.35 - OIS 1Y 0.30 - NLP tone 0.20 (IA) - Dot plot 0.15.

**Formule de Taylor** :
```
i* = r* + pi + 0.5*(pi - pi*) + 0.5*y_gap
```
r* = taux reel neutre (~0.5% Fed) - pi = inflation actuelle - pi* = cible (2%) - y_gap = output gap (vient de D1).

**Taylor gap** : `gap = i*_taylor - i_actual`. gap>0 -> accommodante -> hawkish a venir -> bullish. gap<0 -> restrictive -> dovish -> bearish.

**Piege dangereux - already-priced check** :
```
edge = taylor_gap - ce_que_l_OIS_price_deja
```
Si Taylor dit +0.80% MAIS l'OIS a deja price +1.20% -> la vraie surprise residuelle est BEARISH. Le vrai signal n'est jamais dans le Taylor gap seul.

**Exemple Fed vs BCE** : Fed (r*=0.5,pi=3.2,pi*=2.0,y_gap=+0.9) -> i*=4.75%, actual=5.25% -> gap=-0.50%. BCE (r*=0.25,pi=2.8,pi*=2.0,y_gap=-0.4) -> i*=3.25%, actual=3.75% -> gap=-0.50%. Delta_taylor NEUTRE, mais OIS+ton revelent une divergence invisible au modele seul -> **d2=-0.65** malgre Taylor neutre.

```python
class D2MonetaryScorer:
    def __init__(self):
        self.weights = {'taylor':0.35,'ois':0.30,'tone':0.20,'dot':0.15}
        self.taylor_coefs = {'inflation':0.5,'output':0.5}
    def taylor_rule(self, r_star, pi, pi_target, y_gap):
        return r_star + pi + self.taylor_coefs['inflation']*(pi-pi_target) + self.taylor_coefs['output']*y_gap
    def get_nlp_tone(self, economy):  # SEULE PARTIE IA
        current, previous = perplexity_fetch_cb_statement(economy)
        return claude_extract_tone(current, previous)
    def compute(self, base, quote):
        tg_base = self.taylor_rule(*base.taylor_inputs) - base.policy_rate
        tg_quote = self.taylor_rule(*quote.taylor_inputs) - quote.policy_rate
        diff = {'taylor': zscore(tg_base)-zscore(tg_quote),
                'ois': zscore(base.ois_1y)-zscore(quote.ois_1y),
                'tone': base.nlp_tone - quote.nlp_tone,
                'dot': zscore(base.dot)-zscore(quote.dot)}
        edge = diff['taylor'] - diff['ois']
        raw = sum(self.weights[k]*diff[k] for k in self.weights)
        return {'d2_score': round(np.tanh(raw),3), 'edge': round(edge,3), 'components': diff}
```

**Automatisation** : 2 declencheurs - marche (OIS, continu) + evenements CB (ponctuel, lourd - pipeline NLP tone).

**Pipeline NLP tone** : 1) Perplexity recupere communique actuel+precedent. 2) Claude extrait le ton (mots ajoutes/retires, vote, guidance). 3) Code calibre sur [-1,+1].

**4 pieges** : already-priced (le plus dangereux) - coefficients Taylor fixes a recalibrer - NLP tone subjectif (poids modeste 0.20) - dot plot lent (poids 0.15).

**IA** : usage MOYEN-FAIBLE. 1ere composante ou l'IA travaille a CHAQUE run (mais ciblee sur evenement CB).

**Output** :
```json
{"d2_score": -0.65, "direction": "bearish", "taylor_gap_base": -0.50, "taylor_gap_quote": -0.50,
 "already_priced": true,
 "components": {"delta_taylor_z":0.0,"ois_spread_z":-1.8,"tone_diff":-0.5,"dot_diff_z":-0.9}}
```
-> N2A - Arb 1 (Taylor vs OIS) - Arb 4 (Carry/UIP) - calibrage 2B (Bloc 1 peut reduire poids x0.70).

**Poids par quadrant** : SURCHAUFFE 0.35 (DOMINANT) - GOLDILOCKS 0.15 - STAGFLATION 0.15 - DESINFLATION 0.30.

---

### D3 - L'Inflation & les Anticipations

**Essence** : ne mesure pas l'inflation telle qu'elle est mais les FORCES qui vont la pousser demain - signal AVANCE de D2 a ~3 mois.

**4 blocs (poids)** : CPI+consensus 0.30 - Phillips 0.30 - TIPS breakeven/NAIRU 0.20 - Supercore CPI 0.20.

**Modele Phillips + correction NAIRU** :
```
pi_t = pi_{-1} + alpha*(NAIRU - U3) + (part_neutre - part_actuelle)
```
U3 < NAIRU -> tendu -> pression salariale -> inflation a venir.

**Correction NAIRU** : `U3_corr = U3 + (part_neutre - part_actuelle)`. Pourquoi : Phillips plate depuis ~2010 (gens ont quitte la population active, U3 brut sous-estime le vrai chomage). Rolling ~5 ans, U3 corrige typiquement +1.5% plus haut.

**Arbitrage 2 - le coeur de D3** : `delta = Phillips_forecast - TIPS_breakeven`. delta>0 -> sous-estimation -> hawkish a venir -> BULLISH. delta<0 -> sur-estimation -> BEARISH. Exemple : Phillips 3.3% vs TIPS 2.6% -> delta=+0.7% -> signal avance 3 mois sur D2.

**3 pieges** : toujours core/supercore jamais headline - Phillips plate post-2010 -> correction NAIRU - breakeven TIPS peut etre deconnecte -> comparaison Arb 2.

```python
class D3InflationScorer:
    def __init__(self):
        self.weights = {'cpi_surp':0.30,'phillips':0.30,'nairu':0.20,'tips_trend':0.20}
        self.phillips_alpha = 0.5
        self.nairu_window = 60
    def nairu_corrected(self, u3, part_neutral, part_actual):
        return u3 + (part_neutral - part_actual)
    def phillips_forecast(self, pi_prev, nairu, u3_corr):
        return pi_prev + self.phillips_alpha * (nairu - u3_corr)
    def compute(self, base, quote):
        ph_base = self.phillips_forecast(*base.phillips_inputs)
        ph_quote = self.phillips_forecast(*quote.phillips_inputs)
        arb2_base = ph_base - base.tips_breakeven
        arb2_quote = ph_quote - quote.tips_breakeven
        diff = {'cpi_surp': zscore(base.cpi_surp)-zscore(quote.cpi_surp),
                'phillips': zscore(arb2_base)-zscore(arb2_quote),
                'nairu': zscore(base.nairu_gap)-zscore(quote.nairu_gap),
                'tips_trend': zscore(base.tips_trend)-zscore(quote.tips_trend)}
        raw = sum(self.weights[k]*diff[k] for k in self.weights)
        return {'d3_score': round(np.tanh(raw),3),
                'arb2_delta': round(arb2_base-arb2_quote,3), 'components': diff}
```

**Automatisation** : declenche par N1 (comme D1). TIPS=continu, CPI/Phillips=evenementiel (mensuel). 100% numpy.

**IA** : usage FAIBLE (comme D1). L'IA calibre le MODELE (alpha Phillips, fenetre NAIRU) en conception, jamais dans le run.

**Output** :
```json
{"d3_score": -0.63, "direction": "bearish", "phillips_forecast_base": 2.2, "phillips_forecast_quote": 3.3,
 "arb2_delta": -1.4,
 "components": {"cpi_surp_diff":-1.0,"phillips_diff":-0.7,"nairu_diff":-0.7,"tips_trend_diff":-0.45}}
```
-> N2A - anticipe D2 - Arb 2 (Phillips/TIPS) - calibrage 2B.

**Poids par quadrant** : SURCHAUFFE 0.30 (DOMINANT avec D2) - STAGFLATION 0.25 - GOLDILOCKS 0.15 - DESINFLATION 0.15.

---

### D4 - Le Regime de Risque & Flux (double output, le gatekeeper)

**Essence** : SEULE dimension a double output - un d4_score [-1,+1] qui vote, ET un d4_multiplier [0,1] (le gate) qui multiplie TOUT le resultat final et peut l'annuler.

**5 composantes (poids)** : VIX+kurtosis 0.25 - Yield curve slope 10Y-2Y 0.25 - Dollar funding stress 0.25 - Hedge flows 0.15 - Dollar 2-role 0.10.

**Hysteresis VIX (ENTRY != EXIT, zone morte)** :

| Tier | VIX | kurtosis | carry_mult | fund_mult | score_mult |
|---|---|---|---|---|---|
| GREEN | <15 | <4 | 1.0 | 1.0 | 1.0 |
| YELLOW | 15-24 | 4-6 | 0.7 | 1.0 | 0.7 |
| ORANGE | 24-35 | 6-9 | 0.4 | 0.7 | 0.4 |
| RED | >35 | >9 | 0.0 | 0.3 | 0.0 |

(carry_mult YELLOW/ORANGE mis a jour a 0.7/0.4, cf. section Phase 0).

Seuils exemple : GREEN->YELLOW entry VIX>18, exit VIX<14 (zone morte 14-18). Le kurtosis peut forcer l'escalade : kurtosis>9 -> RED meme si VIX bas (detecte le fat tail AVANT le VIX).

**Preuve historique - Mars 2020** : VIX a 82 -> RED -> d4_multiplier=0 -> tout annule. Capital protege pendant le krach.

**Dollar 2-role** : GREEN/YELLOW -> USD = devise de taux (carry). ORANGE/RED -> USD = refuge (safe haven).

```python
class D4RegimeScorer:
    def __init__(self):
        self.hysteresis = {'green_yellow':{'entry':18,'exit':14},
                            'yellow_orange':{'entry':26,'exit':22},
                            'orange_red':{'entry':37,'exit':33}}
        self.gates = {
            'GREEN':  {'carry':1.0,'fund':1.0,'score':1.0},
            'YELLOW': {'carry':0.7,'fund':1.0,'score':0.7},
            'ORANGE': {'carry':0.4,'fund':0.7,'score':0.4},
            'RED':    {'carry':0.0,'fund':0.3,'score':0.0},
        }
        self.current_regime = 'GREEN'
    def update_regime(self, vix, kurtosis):
        r = self.current_regime; h = self.hysteresis
        if r=='GREEN' and vix>h['green_yellow']['entry']: r='YELLOW'
        elif r=='YELLOW' and vix<h['green_yellow']['exit']: r='GREEN'
        elif r=='YELLOW' and vix>h['yellow_orange']['entry']: r='ORANGE'
        if kurtosis > 9: r = 'RED'
        self.current_regime = r
        return r
    def compute(self, market):
        regime = self.update_regime(market.vix, market.kurtosis)
        gate = self.gates[regime]
        raw = (0.25*market.vix_dir + 0.25*market.yield_curve +
               0.15*market.hedge_flows + 0.10*market.dollar_role)
        d4_score = np.tanh(raw) * gate['score']
        return {'d4_score': round(d4_score,3), 'd4_multiplier': gate['carry'],
                'regime': regime, 'fund_multiplier': gate['fund']}
```

**Automatisation** : SEUL composant "always-on" - temps reel continu, 100% if/else, aucune API lente dans la boucle.

**IA** : ZERO dans la boucle de decision. Conception (calibration seuils, backtest crises 2008/2020/2022) et aval (choix safe haven, post-mortem) seulement. "Agent de risque" != "IA qui decide" - orchestrateur qui tourne le code en continu, appelle l'IA en appoint jamais pour decider.

**Impact du gate sur les arbitrages** : Arb1 x fund_mult - Arb2/3 x1.0 - **Arb4 (carry) x carry_mult, le plus affecte (0 en RED)** - Arb5/6 x risk_mult.

**Output (double)** :
```json
{"d4_score": -0.04, "d4_multiplier": 1.0, "regime": "GREEN", "fund_multiplier": 1.0, "kurtosis": 3.8}
```
-> N2A (score, vote) + gate sur tout le pipeline (multiplier, veto).

---

### D5 - Les Facteurs Structurels

**Essence** : "les fondations de la maison" - mesure la GRAVITE (valeur d'equilibre long terme), pas le mouvement. La plus LENTE du pipeline (miroir de D4) mais la plus puissante.

**4 composantes (poids)** : BEER 0.35 (dominant) - Fiscal impulse 0.25 - Mundell-Fleming 0.20 - Geopolitique 0.20 (IA, la plus profonde).

**Modele BEER** - regression rolling 15 ans sur 3 variables :
- **NFA/PIB** : creancier (NFA+) -> devise forte.
- **ToT** (termes de l'echange) : eleve -> devise forte (ex AUD si minerai cher).
- **r_diff** (taux reels differentiels) : eleve -> attractif.

```
misalignment = spot - juste_valeur_fondamentale
z > +1.5 -> sous-evaluee -> bullish long terme
z < -1.5 -> surevaluee -> bearish long terme
```
Rolling 15 ans (relations structurelles evoluent lentement, fenetre courte capterait du bruit cyclique).

**Mundell-Fleming** (valide G10 flottant uniquement) :

| Politique | Effet devise |
|---|---|
| Fiscal expansion | devise + |
| Fiscal restraint | devise - |
| Monetaire expansion | devise - |
| Monetaire restraint | devise + |

Se brise en EM a controle de capitaux - ne jamais appliquer naivement hors G10.

**Fiscal impulse** : `impulse = deficit_t - deficit_{t-1}`. Ce qui compte est le CHANGEMENT, pas le niveau (Japon -8%/PIB stable = pas de signal ; Delta+2% = signal fort).

**Geopolitique** (seule composante IA) : commerce/tarifs 0.30 - energie/conflits 0.40 - refuge/SWIFT 0.20 - instabilite politique 0.20 -> score z[-1,+1]. Poids plafonne 0.20.

**Agregation** : `d5 = tanh(0.35*BEER + 0.25*fiscal + 0.20*Mundell + 0.20*geopol)`. Exemple EUR/USD : d5~-0.28 (faible, BEER dit EUR sous-evalue mais USD defensif compense).

```python
class D5StructuralScorer:
    def __init__(self):
        self.weights = {'beer':0.35,'fiscal':0.25,'mundell':0.20,'geopol':0.20}
        self.beer_coefs = None
    def beer_fair_value(self, nfa, tot, r_diff):
        c = self.beer_coefs
        return c['nfa']*nfa + c['tot']*tot + c['r_diff']*r_diff + c['const']
    def fiscal_impulse(self, deficit_t, deficit_prev):
        return deficit_t - deficit_prev
    def get_geopol_score(self, economy):  # SEULE PARTIE IA PROFONDE
        research = perplexity_deep_research(f"structural geopolitical risk {economy}")
        return claude_assess_geopol(research)
    def compute(self, base, quote):
        fv_base = self.beer_fair_value(*base.beer_inputs)
        misalign_base = base.spot - fv_base
        diff = {'beer': zscore(misalign_base)-zscore(misalign_quote),
                'fiscal': self.fiscal_impulse(*base.fiscal)-self.fiscal_impulse(*quote.fiscal),
                'mundell': base.mundell_dir - quote.mundell_dir,
                'geopol': base.geopol_score - quote.geopol_score}
        raw = sum(self.weights[k]*diff[k] for k in self.weights)
        return {'d5_score': round(np.tanh(raw),3),
                'beer_misalignment': round(misalign_base-misalign_quote,3), 'components': diff}
```

**Automatisation** : la plus lente (inverse de D4). BEER trimestriel/annuel, fiscal trimestriel, geopol veille continue mais change seulement sur choc structurel.

**Pipeline geopol** : 1) Perplexity Deep Research (multi-angles/sources). 2) Claude calibre le score [-1,+1].

**Miroir D4<->D5** : D4=le plus actif/IA la moins profonde (vitesse prime). D5=le moins actif/IA la plus profonde (le temps le permet).

**Output** :
```json
{"d5_score": -0.28, "direction": "bearish", "beer_misalignment": -1.2, "fiscal_impulse_diff": -0.4,
 "components": {"beer_z":-0.6,"fiscal":-0.4,"mundell_fleming":-0.5,"geopol":-0.9}}
```
-> N2A (poids toujours le plus faible) - Arb 3 (BEER vs spot) - revise Etape 0 (choc geopol peut forcer transition de quadrant).

**Poids par quadrant** : SURCHAUFFE 0.10 - GOLDILOCKS 0.15-0.25 - STAGFLATION 0.10-0.20 - DESINFLATION 0.15. Toujours le poids le plus faible - le socle qui tranche quand tout le reste est neutre.

---

## 7. RECAPITULATIF - REPARTITION IA PAR COMPOSANT (N1 -> D5)

| Etape | Calcul IA en run | Usage IA global | Vitesse |
|---|---|---|---|
| N1 | Non | ELEVE (collecte massive) | lente (ok) |
| Bridgewater | Non | MOYEN (cible) | lente (ok) |
| D2 | Non | NLP tone MOYEN-FAIBLE | moyenne |
| D1 / D3 | Non | FAIBLE | lente/moyenne |
| D4 | Non | TRES FAIBLE | ULTRA-RAPIDE |
| D5 | Non (calcul) / Oui fort (geopol) | LA PLUS PROFONDE | ultra-lente |

**Principe transversal** : plus un composant est mathematique, moins l'IA y a sa place. Perplexity = les yeux. Claude = le cerveau. numpy = la regle (jamais remplacee par de l'IA generative). Chaque dimension utilise l'IA exactement la ou sa temporalite le permet.
