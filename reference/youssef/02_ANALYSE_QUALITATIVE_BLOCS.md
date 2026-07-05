# TERMINAL DE TRADING - CHOLISMO / THE BUILDER
## Fichier 2/3 - Analyse Qualitative (N2B, Blocs 1 a 7)

> Voir aussi : 01_FONDATIONS_ET_ANALYSE_QUANTITATIVE.md (Phase0/Etape0/N1/N2A D1-D5) et 03_SCORING_ARBITRAGES_DECISION.md (N3/N4/N5).

---

## VUE D'ENSEMBLE DU N2B

**Ce que 2B fait** : le 2A (D1-D5) mesure ce qui S'EST PASSE (chiffres, z-scores). Le 2B ANTICIPE ce qui VA SE PASSER (intentions, narratifs, signaux caches, connexions invisibles). 2B ne remplace pas 2A - il voit ce que 2A ne peut pas mesurer, et calibre les poids + la conviction finale.

**Input** : discours CB, prix de marche, flux, evenements geopolitiques, positions (COT).
**Output** : calibrage sur le score 2A brut, conviction finale, wikilinks Obsidian.

**Sequence des 7 blocs** : Bloc 1 (CB 3 niveaux) -> Bloc 2 (narratifs) -> Bloc 3 (cross-market) -> Bloc 4 (geopolitique) -> Bloc 5 (signaux faibles) -> Bloc 6 (10 questions jugement) -> Bloc 7 (calibrage/consolidation) -> N3.

**Regle d'or transversale** : en transition de quadrant Bridgewater -> le qualitatif prime sur le quantitatif. En quadrant stable -> le quantitatif prime, 2B affine et calibre. Le Niveau 3 CB et les signaux faibles sont l'edge le plus durable (ils precedent le marche de 2-6 semaines).

---

## BLOC 1 - LECTURE DES BANQUES CENTRALES (3 niveaux)

**Essence** : le Bloc 1 ne lit pas des chiffres, il lit un DISCOURS. Une seule lecture a trois profondeurs croissantes (pas 3 analyses separees) - comme regarder un tableau : la forme, puis les details, puis l'intention. **Les contradictions entre niveaux sont l'or du bloc.**

### Les 3 niveaux (hierarchie de l'edge : 50 000 -> 500 -> 50 lecteurs)

**Niveau 1 - la surface (deja pricee, 0 edge)** : 1A taux (annonce/change/maintenu) - 1B communique (structure, mots cles) - 1C SEP/dots (projections, mediane, dispersion). Tout le monde le voit en meme temps -> aucun edge, sert de baseline.

**Niveau 2 - ce qui change (edge moyen, ~500 analystes)** - TOUJOURS lu cote a cote avec le communique precedent, 6 signaux :
- 2a adverbes cles : "considerably" -> "somewhat" = pivot dovish qui s'affaiblit.
- 2b ordre des priorites : inflation avant emploi = hawkish ; emploi avant inflation = pivot.
- 2c phrases retirees SANS remplacement : "additional policy firming may be appropriate" retiree = fin du resserrement, signal fort.
- 2d forward guidance modifiee : "we anticipate" -> "we will assess" = moins de certitude.
- 2e qualificatifs economiques retrogrades : "robust" -> "moderate".
- 2f vote et dissidence : dissident hawk en phase dovish = pivot hawkish imminent.

**Niveau 3 - les nuances (edge maximal, ~50 analystes au monde)** - ce qui est OMIS, video obligatoire :
- 3a questions evitees en conference de presse -> CB incertaine sur son endpoint.
- 3b sujets absents du communique -> evitement.
- 3c divergences inter-meetings : hawks qui parlent dovish = pivot tres proche.
- 3d hesitations visibles en video (2-3 sec avant reponse) = incertitude reelle.
- 3e discours non planifie la veille d'une publication = ancrage des attentes.
- 3f working papers sur sujet nouveau = exploration interne discrete.

### La matrice d'interpretation (les combinaisons, pas les niveaux isoles)

| Cas | Combinaison | Interpretation |
|---|---|---|
| CAS 1/4 | 3 niveaux alignes | signal coherent/confluent - FORT et FIABLE |
| CAS 2 | Niv1 hawk + Niv2 dove shift | pivot qui se prepare, NON pricee - L'EDGE |
| CAS 3 | Niv1+2 hawk + Niv3 dove | le corps trahit l'intention |
| CAS 5 | Niv1 hawk + Niv3 dove (omissions) | CONTRADICTION - conflit interne maximal |

### Methode en 5 etapes par reunion CB
1. Lire le communique -> noter les faits bruts (Niv1). 2. Ouvrir le precedent cote a cote -> identifier les 6 signaux de changement (Niv2). 3. Regarder la conference de presse en VIDEO -> hesitations, questions evitees (Niv3). 4. Lire les discours des membres la semaine suivante -> chercher les divergences. 5. Noter dans Obsidian.

**Exemple FOMC nov 2023** : la Fed retire "additional policy firming may be appropriate" sans l'annoncer. Traders Niv1 : "neutre". Traders Niv2 : pivot dovish detecte -> EUR/USD monte 3 jours plus tard, pour les lecteurs Niv2 seulement.

### Le flux temporel - 4 phases (chaque phase ouvre un niveau)

| Phase | Niveaux ouverts | Qui travaille |
|---|---|---|
| AVANT (preparer) | - | Perplexity collecte le precedent, toi identifies 3 choses a surveiller |
| COMMUNIQUE | Niv 1+2 (simultane) | Perplexity compare mot a mot, toi interpretes |
| CONF PRESSE | Niv 2+3 (la video) | Toi seul, le non-dit, le ton (Perplexity n'a pas la video) |
| APRES 48h | Niv 3 pur | Perplexity discours/papers, toi combines la matrice |

### Repartition Perplexity / toi
La ligne n'est PAS "Niv1=Perplexity, Niv3=toi" - c'est **factuel (Perplexity) vs jugement (toi)**, et cette ligne traverse les 3 niveaux :
- **PERPLEXITY (factuel)** : collecte le communique (actuel+precedent), compare mot a mot, liste les discours des membres et working papers. Grounded, jamais de jugement.
- **TOI (jugement)** : interpretes ce que les changements SIGNIFIENT, regardes la video (Niv3), combines les 3 niveaux dans la matrice, calibres.
- Niv1 : Perplexity domine. Niv2 : la ligne passe au milieu. Niv3 : tu domines. La combinaison finale = 100% toi.

**Pas de Brain AI ici** (choix d'architecture volontaire) : le jugement CB n'est pas automatisable fiablement (langage corporel, non-dit, intuition d'un pivot) - une IA qui jugerait ca hallucinerait des pivots. "L'IA augmente le trader, elle ne le remplace pas."

### Output
```json
{
  "bloc1_cb_score": 0.45,
  "direction": "hawkish",
  "divergence_flag": true,
  "divergence_type": "pivot_prepare",
  "confidence": 0.6,
  "matrix_case": 2,
  "priced_in": false,
  "horizon": "court-moyen"
}
```
- **score CB [-1,+1]** : verdict directionnel calibre par toi.
- **flag de divergence** : souvent plus important que le score - detecte le pivot non price.
- **confidence [0,1]** : module le sizing (aligne -> pleine, divergent -> reduite).

**Connexions** : -> autres blocs 2B - confirme/contredit D2 (accord = conviction forte, divergence = l'edge qualitatif voit le pivot avant les chiffres) - calibrage N2B (le flag sur-pondere D2 si pivot non price) - decision N3 (via Arbitrage 1).

**Note Obsidian (6 sections)** : Niveau 1 faits bruts / Niveau 2 changements / Niveau 3 nuances / Synthese combinee (matrice+cas) / Perplexity vs IA (ce qu'il reste a creuser) / Prochains signaux a guetter.

---

## BLOC 2 - LES NARRATIFS DE MARCHE (5 etats)

**Essence** : le marche bouge sur des HISTOIRES, pas seulement des donnees. Identifier l'etat du narratif determine la fiabilite du signal et plafonne (ou non) la conviction.

### Les 5 etats

| Etat | Description | Cap conviction | Action |
|---|---|---|---|
| **Dominant** | consensus fort, momentum, le prix reagit encore | aucun | suivre |
| **Transition** | deux histoires, volatilite elevee | 6/10 | reduire taille 30-50%, attendre |
| **Epuise** ★ le plus rentable | le prix ne reagit plus aux bonnes nouvelles | aucun | contrarian, retournement imminent |
| **Emergent** ★ meilleur timing | nouveau narratif nait, avant consensus | aucun | conviction croissante, R:R ~3:1 |
| **Reflexif** (Soros) ⚠ le plus dangereux | prix<->fondamental en boucle, bulle d'anticipation | **7/10** | plafonner, tail risk pret |

**Test du narratif epuise** : NFP sort a +280k (bullish USD), mais USD baisse ou flat -> les bonnes nouvelles sont deja pricees -> seules les mauvaises restent -> retournement dans 1-3 semaines.

**5 signaux de reflexivite (Soros)** : le prix accelere sans catalyseur fondamental - le COT monte parce que le prix monte - toutes les banques publient le meme target - les medias grand public parlent du trade -> conviction plafonnee a 7/10, tail risk actif des le premier signe de retournement.

### Output
```json
{"etat": "epuise", "cap": null, "action": "contrarian"}
{"etat": "reflexif", "cap": 7, "action": "plafonner"}
```

---

## BLOC 3 - LECTURE CROSS-MARKET (6 correlations)

**Essence** : quand une correlation casse, une force invisible est a l'oeuvre. **Regle fondamentale** : correlation rolling 60 jours ; si elle tombe de +0.7 a +0.2 en 2 semaines = break de correlation = alerte. Ta mission : identifier la force invisible AVANT que le reste du marche la voie -> signal faible.

### Les 6 correlations surveillees

| Paire de marches | Normale | Anormale -> signal |
|---|---|---|
| DXY vs SPX | risk-on = montent ensemble, risk-off = DXY up SPX down | DXY down ET SPX down = crise de confiance US |
| EUR/USD vs spread 10Y | spread US-DE up -> EUR/USD down | spread up MAIS EUR/USD up = force cachee |
| AUD/USD vs SPX | AUD monte quand SPX monte (risk-on) | SPX up mais AUD flat = risk-on US seulement |
| USD/JPY vs VIX | VIX up -> USD/JPY down (JPY safe haven) | VIX up ET USD/JPY up = risque asiatique |
| Gold vs DXY | gold up quand DXY down (inverse) | gold ET DXY up ensemble = inflation structurelle |
| WTI vs CAD | WTI up -> CAD s'apprecie | petrole up, CAD flat = probleme domestique Canada |

**2+ cassures simultanees** -> re-classification du quadrant Etape 0.

### Output
```json
{"breaks": 0, "quadrant_recheck": false}
```

---

## BLOC 4 - GEOPOLITIQUE ET MACRO-POLITIQUE

**Essence** : Perplexity collecte, toi evalues la PERMANENCE. Distinguer l'orage passager du vrai changement de climat.

### 5 types d'evenements
1. Commerce (tarifs, quotas, sanctions, ToT, chaines d'approvisionnement)
2. Politique interieure (elections, changement de gouvernement, instabilite)
3. Conflits militaires (guerres, tensions, sanctions, safe haven flows)
4. Energie et climat (OPEP, transition, ToT importateurs/exportateurs)
5. Systeme monetaire (dedollarisation, BRICS, SWIFT, reserves de change)

### 4 canaux d'impact FX

| Canal | Chemin | Exemple |
|---|---|---|
| Commerce | -> ToT -> D5 (BEER) | guerre commerciale -> ToT du pays cible -> BEER misalignment |
| Capitaux | -> flight to safety -> D4 | conflit -> risk-off flows -> D4 gate active -> JPY/CHF/USD |
| Energie | -> inflation -> D3 -> D2 | crise energie -> CPI up -> CB forcee hawkish -> EUR vulnerable |
| Fiscal | -> depenses -> D5 | depenses militaires/relance -> fiscal impulse -> Mundell-Fleming |

**Regle de permanence** : tarif isole en tweet = temporaire. Guerre commerciale etablie = structurel. Election = structurel SI changement de politique, sinon temporaire. **Plusieurs canaux simultanement = impact amplifie.** 3-4 canaux touches simultanement = reboot complet de l'Etape 0.

### Output
```json
{"permanence": 1, "dim_impact": null}
```
Echelle de permanence : 1 (bruit) a 5 (choc structurel majeur).

---

## BLOC 5 - SIGNAUX FAIBLES (6 categories)

**Essence** : l'edge le plus durable - tu dois les CHERCHER. Info qui vient a toi (headline Bloomberg) = signal fort = deja price. Info que tu dois chercher activement = signal faible = pas encore price. **Ton edge est TOUJOURS dans les signaux faibles.**

### Les 6 categories

| # | Categorie | Exemples de signaux |
|---|---|---|
| 1 | Banques centrales | membre dissident dans un journal regional, economiste Fed publie un working paper nouveau, hawk utilise des formulations dovish, discours non planifie la veille d'une publication |
| 2 | Marche | correlation stable qui casse silencieusement, VIX baisse MAIS RR 25-delta reste negatif, flux TIC (sortie Treasuries sans raison), volume options OTM augmente discretement |
| 3 | Economique | PMI new orders tourne 2-3 mois avant le headline, sentiment PME (pas grandes entreprises), jobless claims +3 semaines consecutives, credit revolving menages accelere |
| 4 | Geopolitique | voyage diplomatique non annonce, modification du langage des communiques G7/G20, banque centrale EM achete de l'or discretement, fonds souverains changent leur allocation devises |
| 5 | Sentiment | put/call ratio options FX change de direction, AAII/Sentix basculent sans raison macro, Google Trends "recession" monte, ton des dirigeants change en earnings calls |
| 6 | Structurel | FMI COFER (diversification des reserves), emissions de dette en devise non-standard augmentent, IDE (investissements directs) changent, flux de remittances expatries changent |

**Regle de convergence** : si 3+ signaux de categories differentes convergent -> la confiance monte significativement (bonus de conviction).

### Frequence de detection systematique
- QUOTIDIEN (5 min) : Sonar "what is unusual in FX today", correlations rolling, bid/ask spread.
- HEBDO (15 min) : working papers Fed/BCE, discours non planifies, COT inhabituels, flux TIC.
- MENSUEL (30 min) : FMI COFER, sentiment institutionnel, correlations 90j, divergences structurelles.

### Output
```json
{"signals": 1, "conviction_bonus": 0}
```

---

## BLOC 6 - LES 10 QUESTIONS DE JUGEMENT (checklist du pilote)

**Essence** : anti-biais, obligatoire avant chaque these finale. Compte les drapeaux rouges. **Le nombre de flags determine le sizing, quelle que soit la beaute du score - c'est le VETO absolu du pipeline.**

### Les 10 questions

**Banques centrales (Q1-Q4)** :
- Q1 : "data-dependent" plus ou moins souvent dans le discours ? (+souvent = incertaine, -souvent = decidee)
- Q2 : hesitations sur les memes questions qu'au dernier meeting ? (oui = debat interne non resolu)
- Q3 : vote unanime ? Si non, qui et pourquoi ? (dissident hawk en phase dovish = pivot imminent)
- Q4 : les membres inter-meetings divergent-ils du communique officiel ?

**Narratif et consensus (Q5-Q7)** :
- Q5 : consensus trop large sur la direction = deja price ? (edge reduit)
- Q6 : le prix reagit-il encore aux donnees ? (si non = narratif epuise, preparer un reversal)
- Q7 : le narratif se nourrit-il lui-meme ? (reflexivite -> conviction max 7/10, tail risk actif)

**Tes propres biais (Q8-Q10)** :
- Q8 : cherches-tu a confirmer ou infirmer ? (force-toi a construire l'argument contraire)
- Q9 : base sur 2 semaines ou 3 mois ? (1 surprise CPI != une tendance)
- Q10 : peux-tu expliquer ta these en 3 phrases SANS chiffres ? (si non, tu ne la comprends pas encore)

### Verdict selon le nombre de flags

| Flags | Decision | size_factor |
|---|---|---|
| 0-2 | trade_full | 1.0 |
| 3-4 | trade_half | 0.5 |
| 5+ | no_trade | 0.0 |

**Le veto absolu** : un score de -0.8 et 7 arbitrages alignes ne valent RIEN si la checklist sort 5+ flags. C'est la protection contre les propres biais du trader (exces de confiance, FOMO, consensus surpeuple, news pas digeree).

### Output
```json
{"flags": 1, "decision": "trade_full", "size_factor": 1.0}
```

---

## BLOC 7 - LE CALIBRAGE (la table de mixage)

**Essence** : le Bloc 7 n'apporte AUCUNE info nouvelle (comme le Bloc 6) - mais la ou le Bloc 6 VERIFIAIT par le jugement, le Bloc 7 INTEGRE par le calcul. Il combine les 6 sorties heterogenes des blocs precedents en UN seul score calibre, pret pour le N3.

**Analogie** : chaque bloc est une piste audio (voix, basse, batterie). L'ingenieur du son (Bloc 7) ne cree aucun son nouveau - il MIXE les pistes existantes dans le bon ordre, aux bons niveaux.

### Les 6 entrees heterogenes (chacune "parle une langue differente")

| Bloc | Apport | Type d'operation |
|---|---|---|
| Bloc 1 | module D2 | modulation de dimension |
| Bloc 2 | narratif -> sizing + mode | multiplicatif (x) |
| Bloc 3 | cross-market -> confiance modeles | multiplicatif (x) |
| Bloc 4 | geopolitique -> dimension ciblee | modulation OU reboot Etape 0 |
| Bloc 5 | signaux -> boost conviction | additif (+ seulement) |
| Bloc 6 | jugement -> verdict | flags (+), plafonds, gate |

### Les 4 types d'operations (la grammaire du mixage)
1. **ADDITIF (+/-)** : ajoute/retire des points. Bloc 5 boost, Bloc 6 flags. S'accumulent.
2. **MULTIPLICATIF (x)** : met a l'echelle, proportionnel. Bloc 3 confiance, Bloc 2 sizing.
3. **PLAFOND (min)** : impose une limite haute. Q7->7/10, Q6->0.75. Applique apres tout le reste via min().
4. **GATE (0/1)** : coupe tout ou laisse passer. D4 crise, Bloc 6 NO-GO. Annule tout.

**Erreur a eviter** : "Bloc 3 reduit la confiance de 50%" n'est PAS "-0.5 point", c'est "x0.5 sur tout le score". Confondre additif et multiplicatif = erreur de calibrage majeure.

### L'ordre des operations (A -> F) - CRUCIAL, change le resultat
- **A** : Score 2A de base (combinaison D1-D5 + gate D4). La "piste brute".
- **B** : Modulations de dimension (Bloc 1, Bloc 4) - s'appliquent en amont, sur les inputs du score.
- **C** : Confiance Bloc 3 [x] - x la fiabilite selon les breaks de correlation. Si le regime casse, on degonfle tout.
- **D** : Calibration narrative Bloc 2 [x] - sizing_mult + mode. S'applique sur le SIZING, pas la direction.
- **E** : Boost conviction Bloc 5 [+] - + si convergence pre-emergente. Ne reduit JAMAIS.
- **F** : Verdict Bloc 6 [+flags, plafonds, gate] - flags (additif) -> plafonds (caps) -> NO-GO (gate). **S'applique EN DERNIER.**

**Regle d'or de l'ordre** : gates et plafonds s'appliquent EN DERNIER. Exemple : conviction 6.0 +2 = 8.0, PUIS cap 7 -> 7.0 (correct). Mais cap d'abord (6) puis +2 = 8.0 (incorrect - le plafond serait contourne).

### Resolution des conflits entre blocs (hierarchie conservatrice : la securite prime)
1. **Les GATES** -> priorite absolue (D4 crise, Bloc 6 NO-GO coupent tout).
2. **Les PLAFONDS** -> priment sur les positifs (Q6->0.75, Q7->7/10 gagnent toujours).
3. **La CONFIANCE objective (Bloc 3)** -> prime sur le jugement narratif (Bloc 2). La preuve chiffree l'emporte sur le ressenti.
4. **Les MODULATIONS & BOOSTS** -> s'appliquent dans l'ordre normal, ce sont les ajustements ordinaires.

**3 conflits typiques** :
- Boost +2 (Bloc5) vs flag -0.5 (Bloc6) : les deux s'appliquent (additif), net = +1.5. Ils ne s'excluent pas.
- Bloc 2 "size up" vs Bloc 3 "casse" : Bloc 3 (mesure objective) prime, on reduit la confiance d'abord.
- Score fort vs Q7 reflexif : le plafond gagne TOUJOURS, peu importe la force. Conviction <= 7/10.

**Biais conservateur volontaire** : tout ce qui REDUIT le risque (gate, plafond, confiance) gagne. Tout ce qui AUGMENTE l'exposition (boost, size up) cede. En cas de doute, on protege.

### Repartition Perplexity / code / toi (le miroir exact du Bloc 6)
- **PERPLEXITY : ABSENT** - le seul bloc sans aucune recherche. Rien a collecter, rien a verifier dehors - le Bloc 7 ne travaille que sur des chiffres deja produits par les blocs precedents.
- **LE CODE : l'executant** - collecte les 6 outputs, applique l'ordre + les operations, resout les conflits, calcule conviction + sizing. Deterministe et tracable.
- **TOI : l'architecte** - EN AMONT tu definis l'ordre, les types, les poids, la hierarchie. EN AVAL tu supervises ("ca a du sens ?"). JAMAIS pendant le calcul.

**Partage TEMPOREL unique** : dans les autres blocs, Perplexity et toi travaillaient EN MEME TEMPS. Ici c'est sequentiel : toi AVANT (concevoir) et APRES (verifier), le code PENDANT (executer). Perplexity : 0% sur toute la ligne.

**Pas de Brain AI - 3 raisons techniques** :
1. Determinisme : memes entrees -> meme sortie obligatoire. Une IA introduirait de la variabilite.
2. Tracabilite : tu dois pouvoir expliquer pourquoi la conviction est 5.6. Une IA serait une boite noire non auditable.
3. La lecon : "concevoir le systeme est humain (toi), l'executer est mecanique (le code)." Un calibrage fiable doit etre delibérement "bete" et deterministe.

### Output - la fiche calibree (l'UNIQUE objet du 2B consomme par le N3)
```json
{
  "conviction_calibree": 5.6,
  "sizing_final": 0.44,
  "direction": "short EUR/USD",
  "gates": {"D4": "open", "nogo": false, "cap_Q6": null, "cap_Q7": null},
  "contributions": {
    "2a_base": 0.65, "b3": 0.85, "b2": 0.90, "b5": 0.5, "b6": -0.5
  },
  "status": "CALIBRE_PRET_N3"
}
```

### Impact - rendre le systeme REPRODUCTIBLE
1. Rend le 2B utilisable : 6 jugements disperses -> 1 score consommable par N3.
2. Garantit la coherence : deux trades similaires calibres pareil -> condition pour comparer et apprendre.
3. Tracable et auditable ⭐ : reconstituer pourquoi 5.6 apres un trade perdant, voir quelle operation a mal pese.
4. Securites systematiques : gates et plafonds appliques mecaniquement, l'emotion ne peut pas les contourner.

**Impact le plus profond** : le Bloc 7 fige le jugement subjectif des autres blocs dans un calcul objectif (memes entrees -> meme sortie). Il transforme le pipeline d'une serie d'intuitions en un vrai SYSTEME. **Cette reproductibilite tracable est LA condition pour passer plus tard aux modeles ML (Phase 4)** - on n'entraine un modele que sur un processus reproductible.

**Place dans le pipeline** : 2A (quanti, D1-D5+gate D4) + 2B (quali, Blocs 1-6 -> Bloc7 calibrage) -> 1 score -> N3 (Flux1 combine quanti+quali -> Flux2 6 arbitrages) -> N4 -> N5. Le Bloc 7 est la charniere qui reduit la complexite de 6 a 1 et condense le qualitatif en une voix prete a dialoguer avec le quantitatif.

---

## SYNTHESE - LE FLUX COMPLET DU N2B (exemple trace, EUR/USD)

```
Bloc 1 : BCE a retire "data-dependent" -> shift dovish (omission Niv3)
         -> {w_D2_modifier: 0.70}
Bloc 2 : narratif "USD fort sur l'inflation" = dominant, pas epuise
         -> {etat: 'dominant', conviction_cap: null}
Bloc 3 : aucune cassure de correlation ce matin
         -> {breaks: 0, quadrant_recheck: false}
Bloc 4 : rien de systemique aujourd'hui -> permanence 1 (bruit)
         -> {permanence: 1, dim_impact: null}
Bloc 5 : 1 signal seul (ISM New Orders), pas de convergence (<3 categories)
         -> {signals: 1, conviction_bonus: 0}
Bloc 6 : 1 flag (consensus un peu surpeuple sur USD) -> trade plein autorise
         -> {flags: 1, decision: 'trade_full'}

Bloc 7 (consolidation) :
{
  "w_D2_modifier": 0.70,   # de B1 : pivot dovish cache
  "score_multiplier": 1.00,
  "conviction_cap": null,  # de B2 : pas de reflexivite
  "b5_bonus": 0,           # de B5 : pas de convergence
  "b6_adjustments": 0.9,   # de B6 : 1 flag, ajustement leger
  "quadrant": "SURCHAUFFE"
}
```
-> Ce package (`w_D2_modifier`, `score_multiplier`, `conviction_cap`, `b6_adjustments`, `quadrant`) est exactement l'input que le **N3 Flux 1** consomme (voir fichier 3).
