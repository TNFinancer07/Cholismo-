# LSR v1.2 — Moteur Quantitatif (D-036)

Moteur autonome **Liquidity Sweep Reversion v1.2** pour Cholismo. Modules TypeScript purs, déterministes, découplés de l'UI.

**Statut : validé.** `npm install && npm run typecheck && npm test` → **88/88 tests verts**, TypeScript `strict` + `noUncheckedIndexedAccess`, 0 erreur.

```
src/
  types.ts        Domaine + OrderFlowSnapshot + contrat LsrTradePlan
  config.ts       Specs CME + calibration PAR INSTRUMENT + presets Apex EOD
  frontiers.ts    Frontières de risque (jour + campagne)
  scanner.ts      F1–F8 + A5b + orchestration Phase 0
  orderflow.ts    Gates B1/B2/B3/B4 (fail-closed, side-aware)
  geometry.ts     A1 entrée · A2 TP borné VPOC · A3 stop bufferisé
  risksizer.ts    Règle /5 + modif VIX + scale-out + ExecutionPlan
  planner.ts      evaluateLsr -> manifeste
  index.ts        API publique + helpers d'état
tests/            88 tests : chaque filtre, chaque gate, géométrie LONG/SHORT,
                  précision /5, presets Apex, robustesse Loop 4
```

---

## ⚠ Contrainte Apex — EOD Trail uniquement

Apex propose deux modèles de drawdown. **Un seul est compatible avec LSR :**

| Modèle Apex | Mécanique | Verdict |
|---|---|---|
| **Intraday Trail** | Le seuil suit le pic d'équité **en temps réel, non réalisé inclus**. Chaque nouveau pic remonte le seuil immédiatement. Pas de DLL. | ⛔ **Rejeté par F1** — le moteur refuse de démarrer |
| **EOD Trail** | Le seuil ne se recalcule qu'à la clôture de session. Les profits papier intrajournaliers ne le déplacent pas. DLL présent. | ✓ Compatible (`EOD_TRAILING`) |

Le préréglage `APEX_EOD_50K` + `apexEodAccount()` construisent un `AccountState` conforme. **Les montants sont à vérifier sur le site Apex le jour de l'achat** (termes commerciaux, sujets à changement).

**Conséquence de sizing** : contrairement à MFF (sans DLL), le DLL Apex devient la **frontière contraignante du jour**. Sur un 50K, `min(plancher 2500, DLL 1000) = 1000` → risque par trade = `1000 / 5 = 200 $`. Le sizing est donc mécaniquement plus serré que sur une firme sans DLL. Couvert par test.

Rappel opérationnel : Apex ne propose plus de reset depuis mars 2026 — un breach impose le rachat d'une évaluation. Le coupe-circuit F8 (arrêt 24 h à 80 % de dd campagne) prend donc une valeur monétaire directe.

---

## Calibration par instrument

Tous les seuils de microstructure sont **dédoublés MES / MNQ** (`config.perInstrument`). Valeurs de 1re passe, à figer sur 60 trades.

| Paramètre | MES | MNQ | Rôle |
|---|---|---|---|
| `f4MaxSpreadTicks` | 1 | 2 | F4 — spread max |
| `f4MinCumulativeDepth` | 150 | 60 | F4 — profondeur top-3, deux côtés |
| `tpMaxTicks` / `tpMinTicks` | 5 / 3 | 8 / 4 | A2 — bornes du TP |
| `tpVpocMarginTicks` | 1 | 1 | A2 — viser N tick avant le VPOC |
| `entryOffsetTicks` | 1 | 1 | A1 — offset d'entrée |
| `entryCancelDistanceTicks` | 3 | 4 | A1 — annulation anti-chasse |
| `slNoiseBufferMin/Max` | 1 / 2 | 2 / 4 | A3 — buffer bruit du stop |
| `b1MinWallRefillRatio` | 0.40 | 0.40 | B1 — rechargement du mur |
| `b2TapeFlipThreshold` | 0.60 | 0.60 | B2 — bascule des agressifs |
| `b3MinDeltaRatio` | 0.30 | 0.30 | B3 — delta/volume signé |
| `b4MaxPostSweepAggression` | 0.30 | 0.30 | B4 — vitesse du sweep |
| `alertDistanceTicks` | 6 | 10 | UI (spec 05) — distance d'alerte |

MNQ est plus rapide et son carnet plus fin : TP et buffers plus larges, exigence de profondeur plus basse. Les quatre seuils order flow sont identiques en 1re passe **par choix** — rien ne justifie encore de les différencier avant mesure.

Globaux (non dédoublés) : `bufferDivisor: 5`, `riskFractionOfCapital: 0.01`, `f2CircuitThreshold: 0.80`, `f3VixHardBlock: 30`, `f3AtrMultiplier: 1.5`, fenêtres F5/F6/F7, seuils F8, `normalMaxTradesPerDay: 10`.

---

## Ordre d'évaluation (fail-fast)

```
garde non-fini -> F1 -> F8-ARRÊT -> F2 -> F6 -> F7 -> F3 -> F5 -> F4
              -> A5b -> F8-restreint/plafond -> B4 -> B1 -> B2 -> B3
              -> géométrie A2/A1/A3 -> RiskSizer /5 -> manifeste
```

F8-ARRÊT passe avant F2 (protection plus forte : halte 24 h contre stop du jour). B4 ouvre les gates order flow — c'est le discriminant le plus fort contre le piège de la continuation.

---

## Intégration driver

Le moteur est **sans effet de bord** : `now` et `state` sont injectés, jamais lus.

```ts
import { evaluateLsr, recordTradeOutcome, freshRuntimeState, apexEodAccount, APEX_EOD_50K } from './lsr-engine/src';

const account = apexEodAccount(APEX_EOD_50K, equityActuelle, equiteOuverture);
const { plan, nextState } = evaluateLsr({ market, account, setup, state, config });
await redis.set(key, nextState);
if (plan.status === 'APPROVED') await broker.submit(plan.executionPlan);
// à la clôture :
const s2 = recordTradeOutcome(nextState, won, Date.now());
```

| Responsabilité | Détenteur |
|---|---|
| Fetch marché/compte, calendrier éco, snapshot order flow | Driver |
| Persistance `LsrRuntimeState` (Redis) | Driver |
| Décision pure (Phase 0 + gates + géométrie + sizing) | **Moteur** |
| Injection broker (Rithmic / NinjaTrader) | Driver |
| `recordTradeOutcome` à la clôture (F6) | Driver |

`RUNTIME_LOOPS.md` = méthodologie de développement, pas un contrat d'API. Le moteur a été produit en **Loop 1** et audité en **Loop 4**.

---

## Conformité Loop 4 (robustesse)

Garde-fou `hasNonFiniteInputs` : tout champ critique non-fini → `INVALID_INPUT`. Double vérification `Number.isFinite(contracts)` dans RiskSizer **et** planner : un plan `APPROVED` ne peut jamais porter `NaN` contrats. Gates order flow fail-closed (mesure absente = rejet). `checkDynamicAtr` fail-closed. F4 sans allocation par tick.

Cas couverts en test : équité `NaN`, VIX `NaN`, ATR `NaN`, plancher `Infinity`, mesures OF hors bornes, stop du mauvais côté de l'entrée, buffer campagne négatif.

---

## Points à trancher

1. **Sens de l'offset A1.** Implémenté : entrée **dans le sens** de la réintégration (LONG → au-dessus du niveau), annulation si le prix repasse de l'autre côté. Inverser le signe de `entryOffsetTicks` si l'intention était l'inverse.
2. **Montants Apex.** `APEX_EOD_50K` porte des ordres de grandeur publics — vérifier et corriger avant achat.
3. **Seuils B1–B4 identiques MES/MNQ.** Volontaire en 1re passe ; à différencier si la calibration montre un écart.
4. **Écartés de la v1.2** : A4 (time-stop) et B5 (sortie anticipée codée). Un trade qui stagne va au SL plein.
