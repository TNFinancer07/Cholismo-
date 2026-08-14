"""LSR v1.2 — couche microstructure : évaluation fail-closed → plan de trade (D-046).

Première couche du câblage du moteur **Liquidity Sweep Reversion** dans Cholismo : elle relie le
détecteur de sweep (D-028) et l'order flow assemblé par l'engine au contrat `TradeManifest`
(D-045). Périmètre STRICT — microstructure et exécution :
- entrées : alerte de sweep, prints du tape, absorption, ratio d'agressifs, carnet L2, VPOC ;
- **ISOLATION (D-046)** : aucune donnée macro, géopolitique, options ou news ici. Les frontières
  compte (F1/F2/F8), volatilité (F3) et calendrier (F5) du doc LSR vivent dans d'autres couches ;
  le RiskSizer /5 exige un `AccountState` → taille fixe `LSR_CONTRACTS` en v1 provisional.

`evaluate_lsr` est **PURE et déterministe** : mêmes entrées → même plan, aucune horloge lue
(`now` injecté, règle commune D-045/LSR), aucun état retenu — un rejet est un `None` SILENCIEUX,
sans calcul résiduel ni allocation conservée. Ordre d'évaluation fail-fast (hérité du doc LSR) :
garde non-finie → déclencheur (sweep frais ET orienté) → B1 (absorption) → B2 (bascule des
agressifs) → F4 (fenêtre de liquidité) → extrême A3 → géométrie A1/A2 → plan.

Mapping des gates (seuils dans `lsr_tuning.PER_INSTRUMENT`, v1 provisional « 1re passe » —
**par instrument** depuis D-069 : MES et MNQ n'ont ni la même densité de carnet ni la même
vitesse, un seuil unique serait faux pour l'un des deux) :
- déclencheur : `BID_SWEEP` (agression vendeuse a balayé le bid) → réversion LONG ;
  `ASK_SWEEP` → SHORT ; alerte sans direction = INORIENTABLE → rejet ;
- B1-like : `absorption is True` — défense du niveau à l'extrême ;
- B2-like : bascule des agressifs côté réversion (LONG : part acheteuse ≥ flip ;
  SHORT : ≤ 1 − flip) ;
- F4-like : spread ≤ max ticks ET profondeur top-3 des DEUX côtés ≥ plancher ;
- A3 : stop = extrême RÉEL du sweep (min/max des prints de la fenêtre) ∓ buffer de bruit —
  jamais une distance fabriquée sans structure. Le buffer est pris à sa borne HAUTE
  (`sl_noise_buffer_max_ticks`) tant que D-070 n'a pas câblé sa version dynamique f(spread, ATR) ;
  la borne haute est le choix prudent (stop plus loin = moins de contrats, jamais plus) ;
- A1 : entrée LIMIT = extrême ± offset, dans le sens de la réintégration ;
- A2 : TP borné [min, max] ticks visant VPOC ∓ marge ; VPOC du mauvais côté ou pas de place →
  rejet (un trade sans chemin vers son objectif n'existe pas).

FAIL-CLOSED (§3) : toute entrée absente, périmée (filtrée en amont par `build_lsr_inputs`,
FRESH only) ou non finie → rejet silencieux. Prix alignés sur la grille `PRICE_TICK`.
Aucun ordre passé (§2.1) : la sortie est un PLAN, revérifié par `manifest_from_lsr_plan`.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from pydantic import BaseModel, Field

from . import config, lsr_tuning
from .lsr_tuning import InstrumentTuning


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class LsrInputs(BaseModel):
    """Photographie STATELESS des entrées microstructure au moment `now` (horloge injectée).
    Tous les champs sont optionnels : l'absence est un état légitime qui mène au rejet, jamais
    à une invention (§3)."""
    now: float
    # Porte F0 (D-050) : état du calendrier macro, calculé par MacroNewsProvider et INJECTÉ ici
    # (la fonction reste pure — amendement documenté de l'isolation D-046). None = couche non
    # câblée → pas de porte ; HARD_LOCK ou SAFETY_UNKNOWN → rejet immédiat.
    news_state: Optional[str] = None
    sweep_ts: Optional[float] = None
    sweep_direction: Optional[str] = None            # BID_SWEEP | ASK_SWEEP | None
    prints: list[dict] = Field(default_factory=list)  # {ts, price, size, side}
    absorption: Optional[bool] = None
    aggressor_ratio: Optional[float] = None          # part acheteuse 0..1
    book: Optional[dict] = None                      # {bids: [[p, s], …], asks: [[p, s], …]}
    vpoc: Optional[float] = None
    # Mesures order flow calculées CHEZ NOUS (D-055/D-056). `orderflow_source` décide qui fait
    # foi pour B1/B2 : "source" (proxys du fournisseur, DÉFAUT et comportement historique) ou
    # "inhouse". La bascule est explicite — changer la source de vérité du chemin d'émission ne
    # doit jamais arriver par effet de bord.
    orderflow: Optional[Any] = None                  # OrderFlowSnapshot | None
    # `None` = « non spécifié » → la source est résolue À L'APPEL depuis la config. Mettre
    # `config.LSR_ORDERFLOW_SOURCE` en défaut de champ le figerait à l'IMPORT du module : toute
    # bascule au runtime (env relue, réglage event-sourcé, essai) resterait sans effet, et le
    # moteur jurerait « [source] » en mode maison. Trouvé par l'essai, pas par un test.
    orderflow_source: Optional[str] = None
    # Instrument évalué (D-069) — décide de la CALIBRATION (`lsr_tuning.PER_INSTRUMENT`). Même
    # doctrine de résolution tardive que `orderflow_source` : `None` = « non spécifié » → lu
    # dans la config À L'APPEL. Un instrument hors table rend le moteur muet, jamais MES par
    # défaut : MNQ jugé aux seuils MES n'émettrait rien, et personne ne saurait pourquoi.
    instrument: Optional[str] = None


def build_lsr_inputs(schema, now: float, news_state: Optional[str] = None,
                     orderflow: Any = None) -> LsrInputs:
    """Extrait les entrées du ContextSchema assemblé — **FRESH uniquement** : une microstructure
    périmée est traitée comme absente (§3), jamais comme un signal. `news_state` (D-050) est
    calculé en amont par le MacroNewsProvider et simplement transporté ici."""
    from .meta import Freshness

    def fresh(meta) -> Any:
        return meta.value if meta is not None and meta.freshness == Freshness.FRESH else None

    s1 = schema.s1_state
    sw = schema.liquidity_sweep
    alert = sw.alert if sw.triggered and sw.alert is not None else None
    tape = fresh(s1.tape)
    return LsrInputs(
        now=now,
        news_state=news_state,
        sweep_ts=alert.ts if alert else None,
        sweep_direction=alert.direction if alert else None,
        prints=tape if isinstance(tape, list) else [],
        absorption=fresh(s1.order_flow.absorption),
        aggressor_ratio=fresh(s1.order_flow.aggressor_ratio),
        book=fresh(s1.order_book),
        vpoc=fresh(s1.structure.vpoc),
        # Mesures maison (D-056) — transportées telles quelles ; c'est `orderflow_source` qui
        # décide si elles font foi, et son défaut est le comportement historique.
        orderflow=orderflow,
    )


def noise_buffer_ticks(spread_ticks: Any, atr_fast: Any, atr_slow: Any,
                       t: InstrumentTuning) -> int:
    """A3 — buffer de bruit du stop, DYNAMIQUE. Port de `geometry.ts::noiseBufferTicks` :

        min(max_ticks, max(min_ticks, ceil(spread)) + (atr_rapide > atr_lent ? 1 : 0))

    Trois idées, dans cet ordre : le stop doit au moins absorber le SPREAD (sinon il se fait
    sortir par le coût d'entrée lui-même) ; il s'élargit d'un tick quand la volatilité est en
    EXPANSION (ATR rapide au-dessus du lent) ; et il reste borné par la calibration de
    l'instrument des deux côtés.

    FAIL-CLOSED, mais dans le sens qui protège (§3) : spread ou ATR non observables →
    **borne haute**. Un stop plus loin, c'est mécaniquement MOINS de contrats — jamais plus.
    Supposer le calme quand on ne voit rien resserrerait le stop pile au mauvais moment."""
    if not _finite(spread_ticks) or spread_ticks < 0:
        return t.sl_noise_buffer_max_ticks
    base = max(t.sl_noise_buffer_min_ticks, math.ceil(float(spread_ticks)))
    if not (_finite(atr_fast) and _finite(atr_slow)):
        return t.sl_noise_buffer_max_ticks           # régime inconnu → on suppose l'expansion
    extra = 1 if float(atr_fast) > float(atr_slow) else 0
    return min(t.sl_noise_buffer_max_ticks, base + extra)


def _setup_id(instrument: Any, sweep_direction: Any, sweep_ts: Any) -> Optional[str]:
    """Identité d'un setup, dérivée du sweep qui lui donne naissance (D-095).

    `None` si le sweep n'est pas identifiable — un identifiant fabriqué ferait passer deux setups
    distincts pour le même, ou l'inverse, et le verrou de re-soumission (F7) porterait à faux.
    La seconde est la granularité : deux évaluations du même sweep à 40 ms d'écart doivent rendre
    le MÊME identifiant, sinon le verrou ne reconnaîtrait jamais une re-soumission.
    """
    if sweep_ts is None or sweep_direction is None or instrument is None:
        return None
    try:
        return f"{instrument}:{sweep_direction}:{int(float(sweep_ts))}"
    except (TypeError, ValueError):
        return None


def _grid(x: float, tick: float) -> float:
    """Aligne un prix sur la grille de ticks (un niveau hors grille n'est pas exécutable)."""
    return round(round(x / tick) * tick, 10)


def _f4_liquidity(book: Any, t: InstrumentTuning, tick: float) -> Optional[float]:
    """F4-like — fenêtre de liquidité : spread borné ET profondeur top-3 des deux côtés.
    Les deux bornes viennent de la calibration de l'INSTRUMENT (D-069) : 1 tick / 150 sur MES
    (carnet dense), 2 ticks / 60 sur MNQ.

    Rend le **spread en ticks** si la fenêtre est ouverte, `None` sinon. Il est rendu plutôt que
    recalculé plus loin parce que le buffer de bruit A3 en dépend (D-070) : deux lectures du
    carnet, c'est deux occasions de ne pas parler du même carnet."""
    if not isinstance(book, dict):
        return None
    bids, asks = book.get("bids"), book.get("asks")
    if not (isinstance(bids, list) and bids and isinstance(asks, list) and asks):
        return None
    try:
        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
        # Marché CROISÉ (bid > ask) ou VERROUILLÉ (bid == ask) : pas de spread tradable — la
        # géométrie ne se construit jamais dessus, même si le détecteur amont a signalé la
        # dislocation (CROSSED_BOOK est un signal D-028, pas un terrain d'exécution).
        if not (math.isfinite(best_bid) and math.isfinite(best_ask) and best_ask > best_bid):
            return None
        spread_ticks = (best_ask - best_bid) / tick
        if spread_ticks > t.f4_max_spread_ticks:
            return None
        # Une profondeur NÉGATIVE est impossible : un carnet qui en porte est corrompu et ne
        # doit pas passer F4 par compensation arithmétique (200 + (−30) ≥ plancher…).
        depth_bid = depth_ask = 0.0
        for level in bids[:3]:
            sz = float(level[1])
            if not (math.isfinite(sz) and sz >= 0):
                return None
            depth_bid += sz
        for level in asks[:3]:
            sz = float(level[1])
            if not (math.isfinite(sz) and sz >= 0):
                return None
            depth_ask += sz
    except (TypeError, ValueError, IndexError):
        return None
    if min(depth_bid, depth_ask) < t.f4_min_cumulative_depth:
        return None
    return spread_ticks


def _sweep_extreme(prints: list, since: float, now: float, is_long: bool) -> Optional[float]:
    """A3 — l'extrême RÉEL touché pendant la fenêtre du sweep (min pour un LONG, max pour un
    SHORT), dérivé des prints. Print sale ignoré : prix non fini OU **≤ 0** (un ES à prix négatif
    est de la corruption, pas une structure), ts non fini OU **daté du futur** (désync d'horloge
    source — même leçon que D-028 : l'heure d'arrivée réelle est inconnue, il ne doit pas ancrer
    la géométrie). Aucun print utilisable → None (pas d'extrême fantôme)."""
    prices = []
    for p in prints:
        if not isinstance(p, dict):
            continue
        price, ts = p.get("price"), p.get("ts")
        if _finite(price) and price > 0 and _finite(ts) and since <= ts <= now:
            prices.append(float(price))
    if not prices:
        return None
    return min(prices) if is_long else max(prices)


def evaluate_lsr(i: LsrInputs) -> Optional[dict]:
    """Évalue un setup de réversion post-sweep. `None` SILENCIEUX dès qu'un critère manque —
    sinon un plan au contrat D-045, prêt pour `manifest_from_lsr_plan`."""
    # -- F0 : HARD LOCK MACRO (D-050) — AVANT toute microstructure. Trader un sweep dans la
    # fenêtre d'une publication USD à fort impact, c'est trader le chaos ; et une couche news
    # câblée mais AVEUGLE (SAFETY_UNKNOWN) vaut un verrou (« on ne trade jamais à l'aveugle »).
    if i.news_state in ("HARD_LOCK", "SAFETY_UNKNOWN"):
        return None
    # -- calibration de l'INSTRUMENT (D-069) : résolue À L'APPEL, jamais à l'import --
    instrument = i.instrument if i.instrument is not None else config.LSR_INSTRUMENT
    t = lsr_tuning.tuning(instrument)
    spec = lsr_tuning.spec(instrument)
    if t is None or spec is None:
        return None                                   # instrument non calibré → aucune géométrie
    tick = spec.tick_size
    # -- déclencheur : sweep FRAIS et ORIENTÉ --
    if not _finite(i.sweep_ts) or not _finite(i.now):
        return None
    if i.now - i.sweep_ts > config.LSR_SWEEP_MAX_AGE_S:
        return None
    if i.sweep_direction not in ("BID_SWEEP", "ASK_SWEEP"):
        return None                                   # inorientable → pas de réversion
    is_long = i.sweep_direction == "BID_SWEEP"        # bid balayé → réversion acheteuse

    # -- B1/B2 : deux SOURCES DE VÉRITÉ possibles, jamais les deux à la fois --
    source = i.orderflow_source if i.orderflow_source is not None else config.LSR_ORDERFLOW_SOURCE
    if source == "source":
        # B1-like : défense du niveau (absorption booléenne du fournisseur).
        if i.absorption is not True:
            return None
        flip = i.aggressor_ratio
    elif source == "inhouse":
        # Mesures maison (D-055). Une porte non calculable n'est pas une porte ouverte : on ne
        # retombe JAMAIS sur les proxys en silence — ce serait la bascule implicite qu'on refuse,
        # à l'envers.
        if i.orderflow is None:
            return None
        refill = getattr(i.orderflow, "wall_refill_ratio", None)
        if not _finite(refill) or refill < t.b1_min_wall_refill_ratio:
            return None
        flip = getattr(i.orderflow, "tape_aggressor_buy_fraction", None)
    else:
        return None                                   # source inconnue → on ne devine pas
    # Une part acheteuse est une FRACTION : hors [0,1] = erreur de flux, quelle que soit son
    # origine. Sans cette borne, un 1.7 corrompu passerait la gate LONG comme un flip
    # « ultra-fort » (§3 : la corruption ne devient jamais un signal).
    if not _finite(flip) or not (0.0 <= flip <= 1.0):
        return None
    if is_long and flip < t.b2_tape_flip_threshold:
        return None
    if not is_long and flip > 1.0 - t.b2_tape_flip_threshold:
        return None
    # -- F3-ATR : PORTÉE (`lsr_frontiers.f3_atr_blocked`) mais PAS CÂBLÉE ICI — voir D-071.
    # Mesuré, pas supposé : le tampon de prints du footprint est borné à `FOOTPRINT_MAX_PRINTS`
    # (≈ 80 s de tape à la cadence du mock), et un ATR-14 sur bougies de 60 s exige 15 bougies,
    # soit ~14 minutes d'historique. Sur 400 ticks de démo : 1 bougie produite, 0 ATR calculable,
    # donc 100 % des snapshots bloqués. La brancher rendrait le moteur DÉFINITIVEMENT muet.
    # Ce qui manque n'est pas la règle, c'est une SOURCE d'ATR — tranche séparée.
    # -- F4-like : fenêtre de liquidité (rend le spread, dont A3 a besoin) --
    spread_ticks = _f4_liquidity(i.book, t, tick)
    if spread_ticks is None:
        return None

    # -- A3 : extrême réel du sweep --
    extreme = _sweep_extreme(i.prints, i.sweep_ts - config.LSR_EXTREME_WINDOW_S, i.now, is_long)
    if extreme is None:
        return None

    # -- A1/A2/A3 : géométrie sur la grille de ticks --
    # VPOC ≤ 0 = corruption (un indice ne cote jamais 0/négatif) : la garde D-045 vérifie
    # l'ORDRE des niveaux, pas leur positivité — elle laisserait passer un ticket négatif cohérent.
    if not _finite(i.vpoc) or i.vpoc <= 0:
        return None
    # A3 (D-070) — le buffer de bruit est DYNAMIQUE : il absorbe le spread réellement coté et
    # s'élargit d'un tick en expansion de volatilité. Les ATR viennent du snapshot maison quand
    # il est là ; sans lui, `noise_buffer_ticks` prend la borne haute (comportement historique).
    sign = 1.0 if is_long else -1.0
    buffer_ticks = noise_buffer_ticks(spread_ticks,
                                      getattr(i.orderflow, "atr_fast", None),
                                      getattr(i.orderflow, "atr_slow", None), t)
    entry = _grid(extreme + sign * t.entry_offset_ticks * tick, tick)
    stop = _grid(extreme - sign * buffer_ticks * tick, tick)
    vpoc = _grid(i.vpoc, tick)
    if is_long:
        if vpoc <= entry:
            return None                               # pas de chemin vers l'objectif
        tp = min(entry + t.tp_max_ticks * tick, vpoc - t.tp_vpoc_margin_ticks * tick)
        if tp < entry + t.tp_min_ticks * tick:
            return None                               # pas de place avant le VPOC
        if not (stop < entry < tp):
            return None
    else:
        if vpoc >= entry:
            return None
        tp = max(entry - t.tp_max_ticks * tick, vpoc + t.tp_vpoc_margin_ticks * tick)
        if tp > entry - t.tp_min_ticks * tick:
            return None
        if not (tp < entry < stop):
            return None

    side = "LONG" if is_long else "SHORT"
    return {
        "status": "APPROVED",
        "instrument": instrument,
        "direction": side,
        "reason": (f"LSR — {i.sweep_direction} réintégré · "
                   f"{'absorption' if source == 'source' else 'mur rechargé'} · "
                   f"flip {flip:.2f} [{source}] · VPOC {vpoc}"),
        "executionPlan": {"entryType": "LIMIT", "entryPrice": entry, "stopLoss": _grid(stop, tick),
                          "takeProfit": _grid(tp, tick), "contracts": config.LSR_CONTRACTS},
        # Provenance du setup, pour les règles de protection F6/F7 (D-095). Additif : le plan
        # portait déjà de quoi EXÉCUTER, pas de quoi se faire REFUSER. Sans ces deux champs, un
        # garde devrait relire `reason` — piloter une gate en analysant une phrase française
        # serait fragile et absurde.
        "protection": {
            # Identité STABLE d'un setup = le sweep dont il naît. Deux évaluations du même sweep
            # rendent le même identifiant : c'est exactement ce que le verrou de re-soumission
            # (F7) doit reconnaître. Convention d'identité, pas une formule.
            "setup_id": _setup_id(instrument, i.sweep_direction, i.sweep_ts),
            "sweep_ts": i.sweep_ts,
        },
    }
